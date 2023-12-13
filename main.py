#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Windows
# Author : Fangyj
# Porject : 相机矫正（视频流与图片融合）

import os, sys
import time
from gui.MyWindow import Ui_MainWindow
from PyQt5 import QtGui, QtWidgets
from PyQt5.QtCore import QTimer, Qt, QRect, QPointF
from PyQt5.QtGui import QImage, QPen
import cv2
import yaml
import numpy as np
import queue
from PIL import Image, ImageDraw, ImageFont
import random
import re
from ffmpeg_read import FFmpegRead
from subprocess import run
from PyQt5.QtGui import QPainterPath
from PyQt5.QtWidgets import  QGraphicsScene, QGraphicsView, QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsLineItem

# 显示视频流
change_img_display_queue = queue.Queue(20)
# 保存图片
save_pic_queue = queue.Queue(10)
# 保存完图片，在pic下拉框新增
pic_ip_queue = queue.Queue(5)
# 拷贝视频流用于融合
copy_change_img_display_queue = queue.Queue(20)
# 融合后的视频流
coin_img_display_queue = queue.Queue(20)

# 当前图片相机的ip
CURRENT_CAMERA_IP = ''
# 保存图片的地址
IMAGE_ROOT_PATH = './images'
# 报错图片
ERROR_PIC = None
# log = HandleLog()

# 中文绘图
def cv2ImgAddText(img, text, left, top, textColor=(0, 255, 0), textSize=20):
    # 判断是否OpenCV图片类型
    if (isinstance(img, np.ndarray)):
        img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    # 创建一个可以在给定图像上绘图的对象
    draw = ImageDraw.Draw(img)
    # 字体的格式
    fontStyle = ImageFont.truetype(
        "font/simsun.ttc", textSize, encoding="utf-8")
    # 绘制文本
    draw.text((left, top), text, textColor, font=fontStyle)
    # 转换回OpenCV格式
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)

ERROR_CAM = 50 * np.ones((500, 700, 3), np.uint8)
ERROR_CAM = cv2ImgAddText(ERROR_CAM, '请检查rtsp是否正确', 75, 200, (255, 255, 255), 60)
ERROR_PIC = 50 * np.ones((500, 700, 3), np.uint8)
ERROR_PIC = cv2ImgAddText(ERROR_PIC, '无法读取该图片', 150, 200, (255, 255, 255), 60)
WORKING_PIC = 50 * np.ones((500, 700, 3), np.uint8)
WORKING_PIC = cv2ImgAddText(WORKING_PIC, '正在读取视频...', 100, 200, (255, 255, 255), 60)
CAMERA_ERR_NOT_PING_PIC = 50 * np.ones((500, 700, 3), np.uint8)
CAMERA_ERR_NOT_PING_PIC = cv2ImgAddText(CAMERA_ERR_NOT_PING_PIC, '相机无法通讯...', 100, 200, (255, 255, 255), 60)

from PyQt5.QtWidgets import QGraphicsScene, QGraphicsView, QGraphicsEllipseItem, QListView

class DrawingScene(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(0, 0, 1, 1)  # 设置场景初始大小
        self.brush = QtGui.QBrush(Qt.red)
        self.pen = QtGui.QPen(Qt.red)
        self.points = []
        self.is_drawing = False

    def mousePressEvent(self, event):
        if not self.is_drawing:
            return
        point = event.scenePos()
        # 调整点坐标以适应场景大小
        x_ratio = point.x() / self.width()
        y_ratio = point.y() / self.height()
        adjusted_point = QPointF(x_ratio, y_ratio)
        self.points.append(adjusted_point)
        if len(self.points) > 1:
            self.draw_lines()
        drawing_item = QGraphicsEllipseItem(point.x() - 5, point.y() - 5, 10, 10)
        drawing_item.setBrush(self.brush)
        drawing_item.setPen(self.pen)
        self.addItem(drawing_item)

    def draw_lines(self):
        path = QPainterPath()
        # 计算相对于场景坐标系的相对坐标
        relative_points = [QPointF(point.x() / self.width(), point.y() / self.height()) for point in self.points]
        path.moveTo(relative_points[0])
        for point in relative_points[1:]:
            path.lineTo(point)
        # 将路径添加到场景
        path_item = QGraphicsPathItem(path)
        path_item.setPen(self.pen)
        self.addItem(path_item)

    def clear_points(self):
        self.points = []
        self.clear()


# 主界面
class MyApp(QtWidgets.QMainWindow, Ui_MainWindow):
    def __init__(self):
        QtWidgets.QMainWindow.__init__(self)
        Ui_MainWindow.__init__(self)
        self.points_yaml_path = './conf/points.yaml'
        # 绘制图片
        self.drawing_scene = DrawingScene()
        self.drawing_view = QGraphicsView(self.drawing_scene)
        self.drawing_view.setGeometry(QRect(0, 0, 561, 431))
        self.drawing_view.setObjectName("drawing_view")
        self.drawing_view.setStyleSheet("background: transparent; border: none;")
        global CURRENT_CAMERA_IP
        self.setupUi(self)
        self.setWindowTitle('摄像头图片标定')
        self.showMaximized()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.read_video)
        self._timer.timeout.connect(self.show_coin_pic)
        self._timer.start(150)
        self.pic_show.resize(237, 149)
        self.camera_show.resize(237, 149)
        self.pic_transparent_slider.setMaximum(100)
        self.pic_transparent_slider.setMinimum(1)
        self.cam_transparent_slider.setMaximum(100)
        self.cam_transparent_slider.setMinimum(1)
        # 参数初始化
        self.pl_path = None
        self.conf_img_ip_list = []
        self.image_index = 0
        self.format_list = [".jpg", ".png", ".jpeg", ".bmp", ".JPG", ".PNG", ".JPEG", ".BMP"]
        self.current_pic_path = None
        self.input_rtsp_user = None
        self.input_rtsp_pwd = None
        self.read_conf()
        self.read_pic_files_path()
        camera_ip_view = self.camera_ip.view()
        if isinstance(camera_ip_view, QListView):
            camera_ip_view.setFixedWidth(self.camera_ip.sizeHint().width())  # 设置与下拉框相同的宽度
        CURRENT_CAMERA_IP = self.camera_ip.currentText()
        self.transparent_ini_sign = True
        # if self.static_camera_ip_len():
        #     self.camera_ip.resize(9999, 20)
        # else:
        #     self.camera_ip.resize(230, 20)
        # 运行视频线程
        self.work_thread = WorkThread(CURRENT_CAMERA_IP)
        self.work_thread.start()
        # 连接
        self.change_pic_btn.clicked.connect(self.next_image)
        self.show_pic_btn.clicked.connect(self.index_ima_dir_path)
        self.pic_ip.currentIndexChanged.connect(self.index_ima_dir_path)
        self.del_pic_btn.clicked.connect(self.del_pic)
        self.camera_show_btn.clicked.connect(self.click_show_camera)
        self.camera_ip.currentIndexChanged.connect(self.click_show_camera)
        self.save_pic_btn.clicked.connect(self.click_save_pic)
        self.pic_transparent_slider.sliderMoved.connect(self.pic_slider_change_val)
        self.cam_transparent_slider.sliderMoved.connect(self.cam_slider_change_val)

        # 绘制图片
        self.pic_coin_camera_show.setLayout(QtWidgets.QVBoxLayout())
        self.pic_coin_camera_show.layout().addWidget(self.drawing_view)
        # 去掉缩放窗口的按钮
        # self.setWindowFlags(Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        # self.setWindowFlags(Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        # 连接绘制按钮点击事件
        self.pushButton.clicked.connect(self.start_drawing)
        self.pushButton_2.clicked.connect(self.clear_drawing)
        self.pushButton_3.clicked.connect(self.save_to_yaml)
        self.pushButton.setEnabled(False)
        # 图片展示
        self.index_ima_dir_path()

    # 禁止调整窗口大小并固定大小
    def resizeEvent(self, event):
        if int(event.size().width()) != 1224:
            self.setFixedSize(event.size())
            self.click_show_pic()

    # 开始绘制
    def start_drawing(self):
        self.drawing_scene.is_drawing = True
        self.pushButton.setEnabled(False)
        self.setCursor(Qt.CrossCursor)

    # 清空绘制
    def clear_drawing(self):
        self.drawing_scene.clear_points()
        self.stop_drawing()

    # 在这里添加保存到yaml的逻辑
    def save_to_yaml(self):
        points = self.drawing_scene.points # 获取绘制的点
        self.stop_drawing()
        self.save_points_to_yaml(points)
        self.index_ima_dir_path()

    def stop_drawing(self):
        self.drawing_scene.is_drawing = False
        self.pushButton.setEnabled(True)
        self.unsetCursor()

    def save_points_to_yaml(self, qpoints):
        try:
            key_to_update = self.image_list[self.image_index]
            if not key_to_update:
                self.warn_message('保存失败')
                return
            # 将 QPointsF 转为普通的 Python 列表
            if not qpoints:
                point_list = [] 
            else:
                point_list = [[point.x(), point.y()] for point in qpoints]

            # 存储到YAML文件
            yaml_data = {
                str(key_to_update): point_list
            }

            try:
                with open(self.points_yaml_path, 'r') as yaml_file:
                    yaml_data = yaml.safe_load(yaml_file)
                    if not yaml_data:
                        yaml_data = {}
            except FileNotFoundError:
                yaml_data = {}

            # 更新或添加键值对
            if yaml_data is not None and key_to_update in yaml_data:
                # 键存在，更新值
                yaml_data[key_to_update] = point_list
            else:
                # 键不存在，追加新的键值对
                yaml_data[key_to_update] = point_list

            # 将更新后的内容写回 YAML 文件
            with open(self.points_yaml_path, 'w') as yaml_file:
                yaml.dump(yaml_data, yaml_file, default_flow_style=False)

            self.info_message('保存成功')
        except Exception as e:
            print('[ERROR] ' + str(e.__traceback__.tb_frame.f_globals['__file__']) + ' ' +str(e.__traceback__.tb_lineno))
            print(e)
            self.warn_message('保存失败')

    # **********************
    # 图片
    # **********************
    # 【点击显示】读取图片路径
    def index_ima_dir_path(self):
        self.image_index = 0
        self.image_list = []
        dir_name = self.pic_ip.currentText()
        self.dir_path = os.path.join(IMAGE_ROOT_PATH, dir_name)
        if not os.path.exists(self.dir_path):
            self.pic_show.setText("未找到当前文件夹：\n" + str(self.dir_path))
            self.pic_current_page.setText('(0/0)') 
            self.setWindowTitle('摄像头图片标定')
        else:
            self.files_list = os.listdir(self.dir_path)
            for m in self.files_list:
                file_type = os.path.splitext(m)[1]
                if file_type in self.format_list:
                    self.image_list.append(m)
            if len(self.image_list) == 0:
                self.pic_show.setText(str(self.dir_path) + "：\n 无符合图片数据")
                self.pic_current_page.setText('(0/0)')
                self.setWindowTitle('摄像头图片标定')
                return -1
            else:
                self.current_pic_path = self.dir_path
        self.click_show_pic()


    def read_pic_files_path(self):
        """
        读取图片路径/也是保存完图片后用于刷新
        """
        conf_img_ip_list_old = self.conf_img_ip_list
        selected_ip = self.pic_ip.currentText()
        self.conf_img_ip_list = []
        if os.path.exists(IMAGE_ROOT_PATH):
            for i in os.listdir(IMAGE_ROOT_PATH):
                if os.path.isdir(os.path.join(IMAGE_ROOT_PATH, i)) and not self.is_folder_empty(os.path.join(IMAGE_ROOT_PATH, i)):
                    self.conf_img_ip_list.append(i)
        if self.conf_img_ip_list != conf_img_ip_list_old:
            self.pic_ip.clear()
            self.pic_ip.addItems(self.conf_img_ip_list)
            if selected_ip in self.conf_img_ip_list:
                self.pic_ip.setCurrentIndex(self.conf_img_ip_list.index(selected_ip))

    def is_folder_empty(self, folder_path):
        try:
            # 获取文件夹中的所有项
            items = os.listdir(folder_path)
            if len(items) == 0:
                os.rmdir(folder_path)
                return True
            else:
                return False
        except FileNotFoundError:
            # 如果文件夹不存在，也视为为空
            return True


    def click_show_pic(self):
        """
        点击刷新图片
        """
        try:
            _image, _image_height, _image_width = self.read_image()
            qimg = QImage(_image.data, _image_width, _image_height, QImage.Format_RGB888)
            position = self.pic_show.size()
            self.pic_show_frame = qimg.scaled(position.width(), position.height(), Qt.IgnoreAspectRatio)
            self.pic_current_page.setText('(' + str(self.image_index + 1) + '/' + str(len(self.image_list)) + ')')
            self.pic_show.setPixmap(QtGui.QPixmap.fromImage(self.pic_show_frame))
            
        except:
            png = cv2.cvtColor(ERROR_PIC, cv2.COLOR_BGR2RGB)
            height, width, channel = png.shape
            bytesperline = 3 * width
            qimg = QImage(png.data, width, height, bytesperline, QImage.Format_RGB888)
            position = self.pic_show.size()
            self.pic_show_frame = qimg.scaled(position.width(), position.height(), Qt.IgnoreAspectRatio)
            self.pic_show.setPixmap(QtGui.QPixmap.fromImage(self.pic_show_frame))
            self.clear_drawing()


    def read_image(self):
        """
        读取图片
        """
        self.clear_drawing()
        _image , height, width = None, None, None
        while self.image_index <= len(self.image_list) - 1:
            time.sleep(0.01)
            try:
                self.pl_path = os.path.join(self.dir_path, self.image_list[self.image_index])
                try:
                    # _image = cv2.imread(str(self.pl_path))
                    _image = cv2.imdecode(np.fromfile(self.pl_path, dtype=np.uint8), cv2.IMREAD_COLOR)
                    load_points = self.from_yaml_read_points_add_to_qlabel()
                    self.draw_green_line_after_load_image(load_points)
                    self.setWindowTitle('摄像头图片标定 - ' + str(self.image_list[self.image_index]))
                    # log.info("切换图片："+ str(self.pl_path))
                except Exception as e:
                    print('[ERROR] ' + str(e.__traceback__.tb_frame.f_globals['__file__']) + ' ' +str(e.__traceback__.tb_lineno))
                    print('ERROR: ' + str(e))
                    _image = cv2.imread(cv2.imdecode(np.fromfile(self.pl_path, dtype=np.uint8), cv2.IMREAD_COLOR))
                    load_points = self.from_yaml_read_points_add_to_qlabel()
                    self.draw_green_line_after_load_image(load_points)
                    self.setWindowTitle('摄像头图片标定 - ' + str(self.image_list[self.image_index]))
                _image = cv2.cvtColor(_image, cv2.COLOR_BGR2RGB)
                height, width, _ = _image.shape
                break
            except:
                self.setWindowTitle('摄像头图片标定')
                self.image_index += 1
        return _image , height, width

    def draw_green_line_after_load_image(self, load_points):
        # 清除之前的图形
        self.drawing_scene.clear()
        # 如果点的数量小于2，无法绘制线，直接返回
        if len(load_points) < 2:
            return
        # 获取第一个点的坐标
        start_point = load_points[0]
        # 遍历剩余的点，依次连接成线
        for point in load_points[1:]:
            end_point = point
            # 创建线条对象
            line_item = QGraphicsLineItem(start_point[0], start_point[1], end_point[0], end_point[1])
            # 设置线条颜色为绿色
            line_item.setPen(QPen(Qt.green))
            # 在场景中添加线条
            self.drawing_scene.addItem(line_item)
            # 将当前点作为下一条线的起点
            start_point = end_point
        # 更新场景
        self.drawing_scene.update()


    def next_image(self):
        """
        下一张图片
        """
        if self.image_index == len(self.image_list) - 1 :
            self.image_index = 0
        else:
            self.image_index += 1
        self.click_show_pic()


    def del_pic(self):
        """
        删除图片
        """
        if self.pl_path and os.path.exists(self.pl_path):
            os.remove(self.pl_path)
            # log.info("删除图片"+ str(self.pl_path))
        self.index_ima_dir_path()

    def from_yaml_read_points_add_to_qlabel(self):
        # 读取现有的 YAML 文件内容
        index_key = self.image_list[self.image_index]
        try:
            with open(self.points_yaml_path, 'r') as yaml_file:
                yaml_data = yaml.safe_load(yaml_file)
        except FileNotFoundError:
            return []

        # 检查键是否存在于配置文件中
        if yaml_data is not None and index_key in yaml_data:
            # 返回键对应的值
            return yaml_data[index_key]
        else:
            return []
    # **********************
    # 视频
    # **********************
    def read_video(self):
        """
         视频帧处理 及 展示
        """
        if not change_img_display_queue.empty():
            frame = change_img_display_queue.get()
            if frame is None:
                frame = ERROR_CAM
            png = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channel = png.shape
            bytesperline = 3 * width
            qimg = QImage(png.data, width, height, bytesperline, QImage.Format_RGB888)
            position = self.camera_show.geometry()
            scared_frame = qimg.scaled(position.width(), position.height(), Qt.IgnoreAspectRatio)
            self.camera_show.setPixmap(QtGui.QPixmap.fromImage(scared_frame))

        if not pic_ip_queue.empty():
            pic_ip_queue.get()
            self.read_pic_files_path()


    def click_show_camera(self):
        """
        切换视频流地址  点击刷新 显示视频流
        """
        self.clear_drawing()
        load_points = self.from_yaml_read_points_add_to_qlabel()
        self.draw_green_line_after_load_image(load_points)
        self.work_thread.__running = False
        global CURRENT_CAMERA_IP
        self.pushButton.setEnabled(False)
        try:
            _ip = parse_rtsp(self.camera_ip.currentText())[2]
            # result = os.system('ping -n 1 -w 1 %s' %_ip)
            result = run('ping -n 1 -w 1 %s' %_ip,shell=True).returncode

            if result == 0:
                image = read_ffmpeg(self.camera_ip.currentText())
                if str(image) == str(None):
                    self.kill_camera_thread()
                    change_img_display_queue.put(ERROR_CAM)
                else:
                    CURRENT_CAMERA_IP = self.camera_ip.currentText()
                    self.work_thread.__running = False
                    self.kill_camera_thread()
                    self.work_thread = WorkThread(CURRENT_CAMERA_IP)
                    self.work_thread.start()
                    self.pushButton.setEnabled(True)
            else:
                self.kill_camera_thread()
                change_img_display_queue.put(CAMERA_ERR_NOT_PING_PIC)
        except:
            change_img_display_queue.put(CAMERA_ERR_NOT_PING_PIC)
            
    def kill_camera_thread(self):
        """
        删除相机的线程
        """
        def _async_raise(tid, exctype):
            """Raises an exception in the threads with id tid"""
            if not inspect.isclass(exctype):
                raise TypeError("Only types can be raised (not instances)")
            res = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(tid), ctypes.py_object(exctype))
            if res == 0:
                raise ValueError("invalid thread id")
            elif res != 1:
                # """if it returns a number greater than one, you're in trouble,
                # and you should call it again with exc=NULL to revert the effect"""
                ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, None)
                raise SystemError("PyThreadState_SetAsyncExc failed")

        def stop_thread(thread):
            _async_raise(thread.ident, SystemExit)
        try:
            self.work_thread.stop_running()
            time.sleep(0.1)
            stop_thread(self.work_thread)
            if self.work_thread.cap:
                self.work_thread.cap.release()
        except Exception as e:
            print("没有进行的线程")


    def click_save_pic(self):
        """
        保存图片的信号
        """
        if save_pic_queue.qsize() > 2:
            save_pic_queue.get()
        save_pic_queue.put(True)


    # **********************
    # 融合视频
    # **********************
    def show_coin_pic(self):
        position = self.pic_coin_camera_show.geometry()
        if self.pl_path and not os.path.exists(self.pl_path):
            self.pushButton.setEnabled(False)
            # self.warn_message('无图片')
            return

        if copy_change_img_display_queue.empty():
            self.pushButton.setEnabled(False)
            # self.warn_message('无视频流')
            _image, _image_height, _image_width = self.read_image()
            if _image_height:
                qimg = QImage(_image.data, _image_width, _image_height, QImage.Format_RGB888)
                scared_frame = qimg.scaled(position.width(), position.height(), Qt.IgnoreAspectRatio)
                if scared_frame:
                    self.pic_coin_camera_show.setPixmap(QtGui.QPixmap.fromImage(scared_frame))
            return

        if self.transparent_ini_sign:
            self.pic_transparent_slider.setValue(self.pic_transparent_slider_val * 100)
            self.cam_transparent_slider.setValue(self.cam_transparent_slider_val * 100)
            self.transparent_ini_sign = False
        
        # 图片
        if self.pl_path:
            pic_frame = cv2.imread(str(self.pl_path))
            pic_frame = cv2.resize(pic_frame, (position.width(), position.height()), interpolation=cv2.INTER_CUBIC)
            # 视频流图片
            cam_qimg = copy_change_img_display_queue.get()
            if cam_qimg is None:
                return
            cam_qimg = cv2.resize(cam_qimg, (position.width(), position.height()), interpolation=cv2.INTER_CUBIC)
            # 融合图片
            coin_frame = cv2.addWeighted(pic_frame, self.pic_transparent_slider_val,  cam_qimg, self.cam_transparent_slider_val, 0, )
            # 处理成qt兼容的图片
            coin_frame = cv2.cvtColor(coin_frame, cv2.COLOR_BGR2RGB)
            height, width, channel = coin_frame.shape
            coin_frame = QImage(coin_frame[:], width, height, width * 3, QImage.Format_RGB888)
            self.pic_coin_camera_show.setPixmap(QtGui.QPixmap.fromImage(coin_frame))
            if not self.drawing_scene.is_drawing and not self.pushButton.isEnabled():
                self.pushButton.setEnabled(True)

    def pic_slider_change_val(self):
        self.pic_transparent_slider_val = self.pic_transparent_slider.value() / 100


    def cam_slider_change_val(self):
        self.cam_transparent_slider_val = self.cam_transparent_slider.value() / 100


    # **********************
    # 通用
    # **********************
    def read_conf(self):
        """
        读取配置文件
        """
        try:
            with open('./conf/config.yaml', 'r', encoding='utf-8') as f_yaml:
                config_dict = yaml.load(f_yaml.read(), Loader=yaml.FullLoader)
                self.conf_rtsp_ip = config_dict['rtsp_ip']
                if self.conf_rtsp_ip:
                    change_img_display_queue.put(WORKING_PIC)
                    self.camera_ip.addItems(self.conf_rtsp_ip)

            with open('./conf/def.yaml', 'r', encoding='utf-8') as f_yaml:
                def_conf_dict = yaml.load(f_yaml.read(), Loader=yaml.FullLoader)
                self.pic_transparent_slider_val = def_conf_dict['pic_transparent_def_val']
                self.cam_transparent_slider_val = def_conf_dict['cam_transparent_def_val']
        except Exception as e:
            print('[ERROR] ' + str(e.__traceback__.tb_frame.f_globals['__file__']) + ' ' +str(e.__traceback__.tb_lineno))
            print(e)
            # log.error('读取配置文件错误')
            # log.error(format(traceback.format_exc()))


    def write_conf(self):
        """
        写入配置文件
        """
        data = {'pic_transparent_def_val' : self.pic_transparent_slider_val,
                'cam_transparent_def_val' : self.cam_transparent_slider_val}
        with open('./conf/def.yaml', 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True)


    def warn_message(self,message):
        """
        警告弹窗
        """
        QtWidgets.QMessageBox.about(self, "关于",
                            message)
    
    def info_message(self,message):
        """
        信息弹窗
        """
        QtWidgets.QMessageBox.information(self, "信息：",
                            message)

    def closeEvent(self, event):
        """
        关闭主程序
        """
        self.write_conf()
        self.kill_camera_thread()
        self.close()

    def static_camera_ip_len(self):
        """
        统计 camera_ip 的长度
        """
        max_len = 0
        if not self.conf_rtsp_ip:
            return None
        for rtsp_ip in self.conf_rtsp_ip:
            if len(rtsp_ip) > max_len:
                max_len = len(rtsp_ip)
        if max_len == 0:
            return None
        else:
            return max_len * 19 * 0.85


# **********************
# 视频线程
# **********************
import inspect
import ctypes
import threading
# import func_timeout
# from func_timeout import func_set_timeout

class WorkThread(threading.Thread):
    def __init__(self, rtsp=None):
        threading.Thread.__init__(self)
        self.rtsp = rtsp
        # print("self.rtsp " + str(self.rtsp))
        self.__running = True


    def stop_running(self):
        """
        暂停程序，杀死线程的时候用
        """
        self.__running = False
        change_img_display_queue.queue.clear()
        change_img_display_queue.put(WORKING_PIC)


    # @func_set_timeout(3)
    def read_camera_rtsp(self, camera_ip_addr):
        """
        读取相机读流
        """
        if self.cap:
            self.cap.release()
        # log.info("切换相机："+ str(camera_ip_addr))
        cap = cv2.VideoCapture(camera_ip_addr, cv2.CAP_FFMPEG)
        return cap


    def run(self):
        """
        将帧塞入队列
        """
        global CURRENT_CAMERA_IP, ERROR_PIC
        # camera_ip_addr = CURRENT_CAMERA_IP
        camera_ip_addr = self.rtsp
        self.cap = ''
        WORKING_frame = WORKING_PIC
        if change_img_display_queue.qsize() > 2:
            change_img_display_queue.get()
        change_img_display_queue.put(WORKING_frame)

        while camera_ip_addr and self.__running:
            time.sleep(0.01)
            if not self.cap:
                image = read_ffmpeg(camera_ip_addr)
                if str(image) == str(None):
                    # log.error(str(self.rtsp) + ' ffmpeg 读流失败')
                    frame = ERROR_CAM
                    if change_img_display_queue.qsize() > 2:
                        change_img_display_queue.get()
                    change_img_display_queue.put(frame)
                else:
                    self.cap = self.read_camera_rtsp(camera_ip_addr)

                if not self.cap:
                    break

            try:
                if not self.cap.isOpened():
                    try:
                        self.cap = self.read_camera_rtsp(camera_ip_addr)
                        ret, frame = self.cap.read()
                    except Exception as e:
                        # log.error(format(traceback.format_exc()))
                        frame = ERROR_CAM
                        if change_img_display_queue.qsize() > 2:
                            change_img_display_queue.get()
                        change_img_display_queue.put(frame)
                        continue
                else:
                    ret, frame = self.cap.read()
                    if not ret:
                        if self.cap:
                            self.cap.release()
            except Exception as e:
                # log.error(format(traceback.format_exc()))
                frame = ERROR_CAM

            if self.rtsp == CURRENT_CAMERA_IP:
                if change_img_display_queue.qsize() > 2:
                    change_img_display_queue.get()
                
                change_img_display_queue.put(frame)

                if copy_change_img_display_queue.qsize() > 2:
                    copy_change_img_display_queue.get()
            
                copy_change_img_display_queue.put(frame)
                self.save_pic_to_dir(camera_ip_addr, frame)
            else:
                break
        else:
            change_img_display_queue.queue.clear()
            change_img_display_queue.put(WORKING_PIC)


    def save_pic_to_dir(self, camera_ip_addr, frame):
        """
        保存图片
        """
        if not save_pic_queue.empty():
            save_pic_queue.get()
            user, passwd, ip = parse_rtsp(camera_ip_addr)
            filestr = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
            fileend = ''
            for m in range(10):
                fileend = fileend + random.choice(filestr)
            time_str = time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(time.time()))
            File_Name_1 = time_str + '_' + '_' + fileend + '.jpg'
            Save_Folder = os.path.join(IMAGE_ROOT_PATH, ip)
            if not os.path.exists(Save_Folder):  # 如果路径不存在 self.Save_Root_Path
                os.makedirs(Save_Folder)
            cv2.imwrite(os.path.join(Save_Folder, File_Name_1), frame)
            pic_ip_queue.put(True)


def parse_rtsp(addr):
    """
    解析 rtsp 数据
    """ 
    pattern = re.compile(r"rtsp://([^:/@]*):?([^:]*)@(\d+.\d+.\d+.\d+)")
    s = pattern.search(addr)
    user, passwd, ip = s.groups()
    return user, passwd, ip


def read_ffmpeg(rtsp):
    ffmpeg_cap = FFmpegRead(rtsp, [1920, 1080])
    ffmpeg_cap.start_read()
    image = ffmpeg_cap.read() # 判断是否是None
    ffmpeg_cap.close_read()
    ffmpeg_cap.clear_queue()
    try:
        return image
    except:
        return None


if __name__ == "__main__":
    # QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    try:
        app = QtWidgets.QApplication(sys.argv)
        window = MyApp()
        window.show()
        sys.exit(app.exec_())
    except Exception as e:
        print('[ERROR] ' + str(e.__traceback__.tb_frame.f_globals['__file__']) + ' ' +str(e.__traceback__.tb_lineno))
        print(e)
        # log.error(format(traceback.format_exc()))
    # image = read_ffmpeg('rtsp://admin:dh123456@172.16.115.137:554/cam/realmonitor?channel=1&subtype=0')
    # print(image)
