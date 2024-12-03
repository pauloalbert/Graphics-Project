import cv2 as cv
import numpy as np
import moderngl as mgl
from logger import LoggerGenerator
import matplotlib.pyplot as plt
import sys
from graph import *
from util import *
from opencv_points import matsToCubes, plot_cubes, alignTrans
from opencv_fit_color import *
from opencv import lsd, prob, drawGraphPipeline, drawEdges
import itertools
#
# New pipeline
#
def edges_to_polar_lines(edges):
    return np.array([(np.sign(np.arctan2(b[0] - a[0], b[1] - a[1]))*(a[1]*b[0]-b[1]*a[0])/np.linalg.norm(b-a), np.fmod(-np.arctan2(b[0] - a[0], b[1] - a[1]) + np.pi,np.pi)) for a, b in edges])

def classifyEdges(edges, threshold_multiplier = 1.2):
    lines = edges_to_polar_lines(edges)

    # Get camera angles
    phi_theta, loss = regress_lines(lines, iterations=1000, refinement_iterations=500, refinement_area=np.deg2rad(15))
    phi, theta = phi_theta
    focal_points = get_focal_points(phi, theta)

    pairs = [(edge, which_line(focal_points, line, threshold = loss * threshold_multiplier)) for edge, line in zip(edges, lines)]
    x_edges = [line for line, which in pairs if which == "x"]
    y_edges = [line for line, which in pairs if which == "y"]
    z_edges = [line for line, which in pairs if which == "z"]
    
    return x_edges, y_edges, z_edges

def smoothEdges(x_edges,y_edges,z_edges):
    x_edges = combineParallelLines(x_edges)
    y_edges = combineParallelLines(y_edges)
    z_edges = combineParallelLines(z_edges)
    return x_edges, y_edges, z_edges

def get_faces_from_pairs(edges1, edges2, threshold = 15):
    faces = []
    indices = []
    for i in range(len(edges1)):
        e1 = edges1[i]
        for j in range(len(edges2)):
            e2 = edges2[j]
            if segments_distance(*e1, *e2) > threshold:
                continue
            for k in range(i + 1, len(edges1)):
                e3 = edges1[k]
                if segments_distance(*e2, *e3) > threshold:
                    continue
                for l in range(j + 1, len(edges2)):
                    e4 = edges2[l]
                    if segments_distance(*e3, *e4) > threshold or segments_distance(*e4, *e1) > threshold:
                        continue

                    # Eliminate duplicate faces:
                    indices.append((i, j, k, l))
                    faces.append([lineIntersection(*e1, *e2), lineIntersection(*e2, *e3), lineIntersection(*e3, *e4), lineIntersection(*e4, *e1)])         
    new_faces = []
    banned_faces = []
    for a, edge_numbers, face in zip(range(len(faces)), indices, faces):
        if edge_numbers in banned_faces:
            continue
        accepted = True
        for b, edge_numbers2, face2 in list(zip(range(len(faces)), indices, faces))[a+1:]:
            # Two faces share two edges.
            if (edge_numbers[0], edge_numbers[2]) == (edge_numbers2[0], edge_numbers2[2]) or (edge_numbers[1], edge_numbers[3]) == (edge_numbers2[1], edge_numbers2[3]):
                # They overlap (significantly)
                if pointInConvexPolygon(sum([np.array(f) for f in face])/4, face2) or pointInConvexPolygon(sum([np.array(f) for f in face2])/4, face):
                    
                    if faceCircumference(face) > faceCircumference(face2):
                        accepted = False
                        break
                    else:
                        banned_faces.append(face2)
        if accepted:
            new_faces.append(face)
    return new_faces

def drawFaces(image, faces, color, shrink_factor = 0.75):
    for face in faces:
        center = sum(np.array(p) for p in face)/4
        cv.fillPoly(image, [np.asarray([shrink_factor * np.array(p) + (1-shrink_factor) * center for p in face],dtype=np.int32)], color)

def drawFocalPointsPipeline(image, edges):
    original_image = image.copy()
    # # # Colored edges drawing # # #
    x_edges, y_edges, z_edges = classifyEdges(edges, 1.2)
    #image = cv.addWeighted(image, 0.5, np.zeros(image.shape, image.dtype), 0.5, 0)
    drawEdges(image, x_edges, (0, 0, 200),1)
    drawEdges(image, y_edges, (0, 100, 0),1)
    drawEdges(image, z_edges, (100, 0, 0),1)

    cv.imshow("Focal points", image)

    # # # MatPlotLib sine wave drawing # # #
    phi_theta, loss = regress_lines(edges_to_polar_lines(edges), iterations=1000, refinement_iterations=500, refinement_area=np.deg2rad(15))
    phi, theta = phi_theta
    draw_vanishing_points_plots(edges_to_polar_lines(edges), phi, theta, show=False)

    image = original_image.copy()
    # # # Connected graph drawing # # #
    x_edges, y_edges, z_edges = smoothEdges(x_edges, y_edges, z_edges)
    drawEdges(image, x_edges, (0, 0, 255),3)
    drawEdges(image, y_edges, (0, 255, 0),3)
    drawEdges(image, z_edges, (255, 0, 0),3)

    zfaces=get_faces_from_pairs(x_edges, y_edges)
    yfaces=get_faces_from_pairs(x_edges, z_edges)
    xfaces=get_faces_from_pairs(z_edges, y_edges)
    
    drawFaces(image, xfaces, (0, 0, 255))
    drawFaces(image, yfaces, (0, 255, 0))
    drawFaces(image, zfaces, (255, 0, 0))
    cv.imshow("Connected Edges", image)
    
    handleClassifiedFaces(original_image.copy(), phi, theta, zfaces, 10000)
    drawEdgeNumbers(original_image.copy(), x_edges, y_edges, z_edges)
    plt.show()

def drawEdgeNumbers(image, x_edges, y_edges, z_edges ):
    for i, edge in enumerate(x_edges):
        cv.putText(image, str(i), (int((edge[0][0] + edge[1][0])/2), int((edge[0][1] + edge[1][1])/2)), cv.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 150), 1)
    for i, edge in enumerate(y_edges):
        cv.putText(image, str(i), (int((edge[0][0] + edge[1][0])/2), int((edge[0][1] + edge[1][1])/2)), cv.FONT_HERSHEY_SIMPLEX, 0.5, (0, 150, 0), 1)
    for i, edge in enumerate(z_edges):
        cv.putText(image, str(i), (int((edge[0][0] + edge[1][0])/2), int((edge[0][1] + edge[1][1])/2)), cv.FONT_HERSHEY_SIMPLEX, 0.5, (150, 0, 0), 1)
    cv.imshow("Edge numbers", image)

def handleClassifiedFaces(image, phi, theta, zfaces, LENGTH = 100000):
    camera_matrix = getIntrinsicsMatrix()
    focal_points = get_focal_points(phi, theta)
    length = LENGTH
    object_points = np.array([[-length,0,0],[0,-length,0],[0,0,length], [0,0,0],[0,1,0],[1,1,0],[1,0,0]], dtype=np.float32)
    for face in zfaces:
        # Face needs to be clockwise!!
        image_points = np.array(focal_points + face,dtype=np.float32)
        ret, rvec, tvec = cv.solvePnP(object_points, image_points, camera_matrix, None)
        tvec = np.array(tvec)
        rvec = np.array(rvec)
        cv.drawFrameAxes(image, camera_matrix, None, rvec, tvec, 1)


    cv.imshow("3D", image)
    return None

def justMatPlotPipeline(image, edges):
    phi_theta, loss = regress_lines(edges_to_polar_lines(edges), iterations=1000, refinement_iterations=500, refinement_area=np.deg2rad(15))
    phi, theta = phi_theta
    draw_vanishing_points_plots(edges_to_polar_lines(edges), phi, theta, show=False)
    plt.show()

from opencv import handleFaces
def facesToTrans(xfaces, yfaces,zfaces):
    return handleFaces(np.array(xfaces + yfaces + zfaces))

def getCubesVP(edges):
    x_edges, y_edges, z_edges = classifyEdges(edges, 1.2)
    x_edges, y_edges, z_edges = smoothEdges(x_edges, y_edges, z_edges)
    zfaces=get_faces_from_pairs(x_edges, y_edges)
    yfaces=get_faces_from_pairs(x_edges, z_edges)
    xfaces=get_faces_from_pairs(z_edges, y_edges)
    trans = facesToTrans(xfaces, yfaces, zfaces)
    return trans

if __name__ == "__main__":
    file = "sc_pres.png"
    image = cv.imread(file)
    drawFocalPointsPipeline(image, lsd(image))

    cv.waitKey(0)
    cv.destroyAllWindows()