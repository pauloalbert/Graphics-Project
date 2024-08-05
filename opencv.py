import cv2 as cv
import numpy as np
import moderngl as mgl

def opencv_process(ctx):
    # Get the screen as a buffer
    buffer = ctx.screen.read(components=3,dtype="f4")
    raw = np.frombuffer(buffer,dtype="f4")
    image = raw.reshape((ctx.screen.height,ctx.screen.width,3))[::-1,:,::-1]

    gray = cv.cvtColor(image, cv.COLOR_BGR2GRAY)
    blue_channel, green_channel, red_channel = cv.split(image)
    # Apply GaussianBlur to reduce noise and improve contour detection

    def get_edges_image(image, blur = (5, 5),thresh1 = 5, thresh2 = 10):
        blurred = cv.GaussianBlur(image, blur, 0)
        return cv.Canny(blurred.astype(np.uint8), thresh1, thresh2)

    #canny_split = cv.cvtColor(cv.merge([get_edges_image(blue_channel),get_edges_image(red_channel),get_edges_image(green_channel)]),cv.COLOR_BGR2GRAY)
    canny = get_edges_image(gray)
    #image = cv.merge([get_edges_image(blue_channel),get_edges_image(red_channel),get_edges_image(green_channel)])
    lines = cv.HoughLinesP(canny, 1, np.pi/180, threshold=60, minLineLength=50, maxLineGap=10)

    overlay = np.zeros_like(image)
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            cv.line(overlay, (x1, y1), (x2, y2), (0, 0, 255), 2)
