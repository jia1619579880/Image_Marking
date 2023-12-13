import cv2
import numpy as np
import sys
from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
import os, sys
from attr import s

from matplotlib.image import imread
from gui.MyWindow import Ui_MainWindow
from PyQt5 import QtCore, QtGui, uic, QtWidgets
from PyQt5.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QImage
import cv2
import glob
import yaml
from termcolor import colored
class Video():
    def __init__(self, capture):
        self.capture = capture
        self.currentFrame = np.array([])
    def captureNextFrame(self):
        ret, readFrame = self.capture.read()
        if (ret == True):
            self.currentFrame = cv2.resize(readFrame, (960, 540))
    def convertFrame(self):
        try:
            height, width, channel = self.currentFrame.shape
            bytesPerLine = 3 * width
            qImg = QImage(self.currentFrame.data, width, height, bytesPerLine,
                               QImage.Format_RGB888).rgbSwapped()
            qImg = QtGui.QPixmap.fromImage(qImg)
            return qImg
        except:
            return None
class win(QtWidgets.QMainWindow):
    def __init__(self, parent=None):
        super().__init__()
        self.setGeometry(250, 80, 800, 600)  # 从屏幕(250，80)开始建立一个800*600的界面
        self.setWindowTitle('camera')
        self.videoPath = "rtsp://admin:2021aifjeport@172.16.115.130:554/"
        self.video = Video(cv2.VideoCapture(self.videoPath))
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.play)
        self._timer.start(27)
        self.update()
        self.videoFrame = QtWidgets.QLabel('VideoCapture')
        self.videoFrame.setAlignment(Qt.AlignCenter)
        self.setCentralWidget(self.videoFrame)          # 设置图像数据填充控件
    def play(self):
        try:
            self.video.captureNextFrame()
            self.videoFrame.setPixmap(self.video.convertFrame())
            self.videoFrame.setScaledContents(True)     # 设置图像自动填充控件
        except TypeError:
            print('No Frame')
if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    win = win()
    win.show()
    sys.exit(app.exec_())