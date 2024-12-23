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
from opencv import lsd, prob, drawGraphPipeline, drawEdges, drawLinesColorful
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
    
    return x_edges, y_edges, z_edges, phi, theta

def _splitEdges(base, cutters, threshold = 0.1):
    new_edges = []
    for edge in base:
        intersection = None
        for other_edge in cutters:
            t, s = get_segments_intersection(*edge, *other_edge)
            if s is None or t is None:
                continue
            if s > -threshold and s < 1 + threshold and t >= 0.19 and t <= 0.81:
                intersection = edge[0] + t * (edge[1] - edge[0])
                break
    
        if intersection is not None:
            new_edges.append([edge[0], intersection])
            new_edges.append([intersection, edge[1]])
            continue
        new_edges.append(edge)
    return new_edges

def splitEdges(x_edges, y_edges, z_edges, threshold = 0.1):
    return _splitEdges(x_edges, y_edges+z_edges, threshold), _splitEdges(y_edges, z_edges+x_edges, threshold), _splitEdges(z_edges, x_edges+y_edges, threshold)
        
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

    # Orient clockwise
    new_new_faces = []
    for face in new_faces:
        e1 = [face[1][0] - face[0][0], face[1][1] - face[0][1]]
        e2 = [face[2][0] - face[1][0], face[2][1] - face[1][1]]
        if e1[0]*e2[0] - e1[1]*e2[0] < 0:
            new_new_faces.append(face)
        else:
            new_new_faces.append(face[::-1])
    return new_new_faces

def drawFaces(image, faces, color, shrink_factor = 0.75):
    for face in faces:
        center = sum(np.array(p) for p in face)/4
        # cv.line(image, np.array(face[0],dtype=np.uint32), np.array(face[1],dtype=np.uint32), (0.5*color[0],0.5*color[1],0.5*color[2]), 3)
        # cv.line(image, np.array(face[1],dtype=np.uint32), np.array((np.array(face[2])+face[1])/2,dtype=np.uint32), (0.5*color[0],0.5*color[1],0.5*color[2]), 3)
        cv.fillPoly(image, [np.asarray([shrink_factor * np.array(p) + (1-shrink_factor) * center for p in face],dtype=np.int32)], color)

def drawMats(image, mats):
    for rvec, tvec in mats:
        cv.drawFrameAxes(image, getIntrinsicsMatrix(), None, rvec, tvec, 1)
    cv.imshow("Mats"+str(np.random.rand()), image)

import matplotlib.pyplot as plt
def draw3dEdges(edges_3d):
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')
    plt.title("Y axis edges in 3D")
    ax.scatter([0],[0],[0],c='b')
    ax.set_xlabel("z")
    ax.set_ylabel("x")
    ax.set_zlabel("y")
    for edge in edges_3d:
        color = 'k'
        length =  np.linalg.norm(np.array(edge[1]) - edge[0])
        if abs(np.dot(np.array(edge[1]) - edge[0], np.array([0,0,1]))) / length > 0.93:
            color = 'b'
        elif abs(np.dot(np.array(edge[1]) - edge[0], np.array([0,1,0]))) / length > 0.93:
            color = 'g'
        elif abs(np.dot(np.array(edge[1]) - edge[0], np.array([1,0,0]))) / length > 0.93:
            color = 'r'
        ax.plot([edge[0][2], edge[1][2]], [edge[0][0], edge[1][0]], [edge[0][1], edge[1][1]], color = color)
    plt.show()

def drawFocalPointsPipeline(image, edges):
    original_image = image.copy()
    # # # Colored edges drawing # # #
    x_edges, y_edges, z_edges, phi, theta = classifyEdges(edges, 1.2)

    #image = cv.addWeighted(image, 0.5, np.zeros(image.shape, image.dtype), 0.5, 0)
    drawEdges(image, x_edges, (0, 0, 200),1)
    drawEdges(image, y_edges, (0, 100, 0),1)
    drawEdges(image, z_edges, (100, 0, 0),1)
    
    # cv.imshow("Focal points", image)
    loss = get_camera_angles(image, iterations = 500, method="lsd")
    draw_vanishing_waves(image, *loss, show=False)

    # # # MatPlotLib sine wave drawing # # #
    # draw_vanishing_points_plots(edges_to_polar_lines(edges), phi, theta, show=False)

    image = original_image.copy()
    # # # Connected graph drawing # # #
    x_edges, y_edges, z_edges = smoothEdges(x_edges, y_edges, z_edges)
    # drawEdges(image, x_edges, (0, 0, 255),3)
    # drawEdges(image, y_edges, (0, 255, 0),3)
    # drawEdges(image, z_edges, (255, 0, 0),3)
    # drawLinesColorful(original_image.copy(), x_edges + y_edges + z_edges, "colorful")

    threshold = 0.1
    x_edges, y_edges, z_edges = splitEdges(x_edges, y_edges, z_edges, threshold)   
    drawLinesColorful(original_image.copy(), x_edges + y_edges + z_edges, "Detected edges in image")
    
    zfaces=get_faces_from_pairs(x_edges, y_edges)
    yfaces=get_faces_from_pairs(z_edges, x_edges)
    xfaces=get_faces_from_pairs(y_edges, z_edges)
    
    # drawFaces(image, xfaces, (0, 0, 255))
    # drawFaces(image, yfaces, (0, 255, 0))
    # drawFaces(image, zfaces, (255, 0, 0))
    # cv.imshow("Connected Edges", image)
    
    edges_3d = edgesTo3D(phi, theta, x_edges, y_edges, z_edges)
    # d1, _ = edgesTo3D(phi, 0, x_edges, y_edges, z_edges)
    # d3, _ = edgesTo3D(np.pi/2, theta, x_edges, y_edges, z_edges)

# + [(0.3* a, 0.3*b) for a,b in original_3d] + [(0.5* a, 0.5*b) for a,b in d1] + [(0.7* a, 0.7*b) for a,b in d3]
    draw3dEdges(edges_3d)
    print(edges_3d)
    # MAts method
    # drawMats(original_image.copy(), handleClassifiedFaces(phi, theta, zfaces, "z", 9000000))
    # drawMats(original_image.copy(), handleClassifiedFaces(phi, theta, xfaces, "x", 9000000))
    # drawMats(original_image.copy(), handleClassifiedFaces(phi, theta, yfaces, "y", 9000000))

     # Edge numbers
    # drawEdgeNumbers(original_image.copy(), x_edges, y_edges, z_edges)
    plt.show()

def drawEdgeNumbers(image, x_edges, y_edges, z_edges ):
    for i, edge in enumerate(x_edges):
        cv.putText(image, str(i), (int((edge[0][0] + edge[1][0])/2), int((edge[0][1] + edge[1][1])/2)), cv.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 150), 1)
    for i, edge in enumerate(y_edges):
        cv.putText(image, str(i), (int((edge[0][0] + edge[1][0])/2), int((edge[0][1] + edge[1][1])/2)), cv.FONT_HERSHEY_SIMPLEX, 0.5, (0, 150, 0), 1)
    for i, edge in enumerate(z_edges):
        cv.putText(image, str(i), (int((edge[0][0] + edge[1][0])/2), int((edge[0][1] + edge[1][1])/2)), cv.FONT_HERSHEY_SIMPLEX, 0.5, (150, 0, 0), 1)
    cv.imshow("Edge numbers", image)

def handleClassifiedFaces(phi, theta, zfaces, axis, LENGTH = 9000000):
    def randomsign():
        return 1 if np.random.rand() > 0.5 else -1
    if axis == "z":
        shape = [[0,0,0],[0,1,0],[1,1,0],[1,0,0]]
    elif axis == "y":
        shape = [[0,0,0],[1,0,0],[1,0,1],[0,0,1]]
    else:
        shape = [[0,0,0],[0,0,1],[0,1,1],[0,1,0]]
    camera_matrix = getIntrinsicsMatrix()
    focal_points = get_focal_points(phi, theta)
    length = LENGTH
    object_points = np.array([[-length,0,0],[0,length,0],[0,0,length]] + shape, dtype=np.float32)
    mats = []
    for face in zfaces:
        for iter in range(50):
            # Face needs to be clockwise!!
            image_points = [focal_points + face]
            rand_object_point =  np.array([[randomsign()*a for a in p] for p in [[-length,0,0],[0,length,0],[0,0,length]]] + shape,dtype=np.float32)
            rand_image_point = image_points[::randomsign()]
            offset = np.random.randint(0,3)
            rand_image_point = np.array(image_points[offset:] + image_points[:offset],dtype=np.float32)
            ret, rvec, tvec = cv.solvePnP(rand_object_point, rand_image_point, camera_matrix, None)
            tvec = np.array(tvec)
            rvec = np.array(rvec)
            if np.linalg.norm(tvec) < 1000 and np.linalg.norm(tvec) > 0.01:
                break
        mats.append((rvec, tvec))

    return mats

def justMatPlotPipeline(image, edges):
    phi_theta, loss = regress_lines(edges_to_polar_lines(edges), iterations=1000, refinement_iterations=500, refinement_area=np.deg2rad(15))
    phi, theta = phi_theta
    draw_vanishing_points_plots(edges_to_polar_lines(edges), phi, theta, show=False)
    plt.show()

def facesToTrans(xfaces, yfaces,zfaces, phi, theta):
    xmats = handleClassifiedFaces(phi, theta, xfaces, "x")
    ymats = handleClassifiedFaces(phi, theta, yfaces, "y")
    zmats = handleClassifiedFaces(phi, theta, zfaces, "z")
    def transformPoint(point, rvec, tvec):
        return cv.Rodrigues(rvec)[0] @ np.array(point) + tvec
    points = []
    for mat in xmats:
        points.append(max(transformPoint([0.5,0.5,0.5], *mat), transformPoint([-0.5,0.5,0.5], *mat), key = lambda x: np.linalg.norm(x)))
        
    for mat in ymats:
        points.append(max(transformPoint([0.5,0.5,0.5], *mat), transformPoint([0.5,-0.5,0.5], *mat), key = lambda x: np.linalg.norm(x)))
    for mat in zmats:
        points.append(max(transformPoint([0.5,0.5,0.5], *mat), transformPoint([0.5,0.5,-0.5], *mat), key = lambda x: np.linalg.norm(x)))

    return points


def getCubesVP(edges):
    x_edges, y_edges, z_edges, phi, theta = classifyEdges(edges, 1.2)
    x_edges, y_edges, z_edges = smoothEdges(x_edges, y_edges, z_edges)
    zfaces=get_faces_from_pairs(x_edges, y_edges)
    yfaces=get_faces_from_pairs(x_edges, z_edges)
    xfaces=get_faces_from_pairs(z_edges, y_edges)
    centers = facesToTrans(xfaces, yfaces, zfaces, phi, theta)
    return centers

from opencv import handleFaces
def getCubesMixed(edges):
    x_edges, y_edges, z_edges, phi, theta = classifyEdges(edges, 1.2)
    x_edges, y_edges, z_edges = smoothEdges(x_edges, y_edges, z_edges)
    zfaces=get_faces_from_pairs(x_edges, y_edges)
    yfaces=get_faces_from_pairs(x_edges, z_edges)
    xfaces=get_faces_from_pairs(z_edges, y_edges)
    trans = handleFaces([np.array(face,dtype=np.float32) for face in xfaces + yfaces + zfaces])
    return trans

def drawMixedPipeline(image, edges):
    
    original_image = image.copy()
    # # # Colored edges drawing # # #
    x_edges, y_edges, z_edges, phi, theta = classifyEdges(edges, 1.2)

    #image = cv.addWeighted(image, 0.5, np.zeros(image.shape, image.dtype), 0.5, 0)
    drawEdges(image, x_edges, (0, 0, 200),1)
    drawEdges(image, y_edges, (0, 100, 0),1)
    drawEdges(image, z_edges, (100, 0, 0),1)
    
    cv.imshow("Focal points", image)


    image = original_image.copy()
    # # # Connected graph drawing # # #
    x_edges, y_edges, z_edges = smoothEdges(x_edges, y_edges, z_edges)
    drawEdges(image, x_edges, (0, 0, 255),3)
    drawEdges(image, y_edges, (0, 255, 0),3)
    drawEdges(image, z_edges, (255, 0, 0),3)
    drawLinesColorful(original_image.copy(), x_edges + y_edges + z_edges, "colorful")

    threshold = 0.1
    x_edges, y_edges, z_edges = splitEdges(x_edges, y_edges, z_edges, threshold)   
    drawLinesColorful(original_image.copy(), x_edges + y_edges + z_edges, "colorful_split")
    
    zfaces=get_faces_from_pairs(x_edges, y_edges)
    yfaces=get_faces_from_pairs(z_edges, x_edges)
    xfaces=get_faces_from_pairs(y_edges, z_edges)
    
    drawFaces(image, xfaces, (0, 0, 255))
    drawFaces(image, yfaces, (0, 255, 0))
    drawFaces(image, zfaces, (255, 0, 0))
    cv.imshow("Connected Edges", image)

    
    trans = handleFaces([np.array(face,dtype=np.float32) for face in xfaces + yfaces + zfaces])
    mats, excluded_mats = alignTrans(trans)

    points = matsToCubes(mats)
    plot_cubes(points)
    


# # # NEW METHOD # # #
def pixelToPlane(pixel,camera_intrinsics = None, projection_matrix = None):
    if camera_intrinsics == None:
        camera_intrinsics = getIntrinsicsMatrix()
    if projection_matrix == None:
        projection_matrix = np.eye(3)
        projection_matrix[0,0] = camera_intrinsics[0,2] / camera_intrinsics[1,2]
    screen_point = np.linalg.inv(projection_matrix) @ np.linalg.inv(camera_intrinsics) @ np.array([pixel[0], pixel[1], 1])
    return np.array([-screen_point[0], -screen_point[1], 1])

def rotateScreen(screen_point, phi, theta):
    
    rotation_matrix = np.array([
        [np.cos(theta), 0, -np.sin(theta)],
        [0, 1, 0],
        [np.sin(theta), 0, np.cos(theta)]
    ]) @    np.array([
        [1, 0, 0],
        [0,np.cos(phi), -np.sin(phi)],
        [0,np.sin(phi), np.cos(phi)]
    ])
    return rotation_matrix @ screen_point

def cartesianToPolar(vector):
    phi = np.arctan2(vector[1], vector[0])
    theta = np.arctan2(vector[2],vector[0])
    
    return phi, theta, np.linalg.norm(vector)

def get_view_angles(point, screen_width=WIDTH, screen_height=HEIGHT, x_fov = 90):
    x_angle = np.deg2rad(x_fov)*(point[0]/screen_width - 1/2)
    y_angle = np.deg2rad(screen_height*x_fov/screen_width)*(point[1]/screen_height - 1/2)
    return x_angle, y_angle

def get_angle_between_vectors(p1, p2):
    return np.arccos( np.dot(p1, p2) / (np.linalg.norm(p1) * np.linalg.norm(p2)) )

def edgeTo3D(edge, axis, camera_phi, camera_theta):
    if axis == "x":
        third_side = np.array([-1,0,0])
    elif axis == "y":
        third_side = np.array([0,1,0])
    else:
        third_side = np.array([0,0,1])
    p1 = rotateScreen(pixelToPlane(edge[0]), -camera_phi, -camera_theta)
    p2 = rotateScreen(pixelToPlane(edge[1]), -camera_phi, -camera_theta)
    original_angle = np.arccos( np.dot(p1, p2) / (np.linalg.norm(p1) * np.linalg.norm(p2)) )
    p1_angle = get_angle_between_vectors(p1, np.array(third_side))
    p2_angle = get_angle_between_vectors(p2, np.array(third_side))
    p2_length = np.sin(p1_angle) / np.sin(original_angle) * 1
    p2 = p2_length * p2 / np.linalg.norm(p2)
    p1_length =np.sin(p2_angle) / np.sin(original_angle) * 1
    p1 = p1_length * p1 / np.linalg.norm(p1)
    # print("OFFSET:", min(np.linalg.norm(p2 - p1 - third_side),np.linalg.norm(p1 - p2 - third_side)))
    if p1_length > 10 or p2_length > 10:
        return None
    return [p1, p2]

def edgesTo3D(camera_phi, camera_theta, x_edges, y_edges, z_edges):
    camera_phi = np.pi/2 - camera_phi
    edges_3d = []
    for edge in y_edges:
        # Triangle ORIGIN A B
        edge = edgeTo3D(edge, "y", camera_phi, camera_theta)
        if edge is not None:
            edges_3d.append(edge)
        
    for edge in x_edges:
        # Triangle ORIGIN A B
        edge = edgeTo3D(edge, "x", camera_phi, camera_theta)
        if edge is not None:
            edges_3d.append(edge)

    for edge in z_edges:
        #Triangle ORIGIN A B
        edge = edgeTo3D(edge, "z", camera_phi, camera_theta)
        if edge is not None:
            edge = [edge[0]/1.5, edge[1]/1.5]
            edges_3d.append(edge)
    return edges_3d

def getEdgesVP(edges):
    x_edges, y_edges, z_edges, phi, theta = classifyEdges(edges, 1.2)
    x_edges, y_edges, z_edges = smoothEdges(x_edges, y_edges, z_edges)
    edges_3d = edgesTo3D(phi, theta, x_edges, y_edges, z_edges)
    return edges_3d

if __name__ == "__main__":
    file = 'generated_images/demo_scarce.png'
    image = cv.imread(file)
    drawFocalPointsPipeline(image, lsd(image))

    cv.waitKey(0)
    cv.destroyAllWindows()