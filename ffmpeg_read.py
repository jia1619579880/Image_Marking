#############################################
##### 使用FFMPEG读流类
#############################################
import os
import time
import queue
import signal
import collections
import threading
import traceback
import numpy as np
import subprocess as sp
from camera_base import CameraBase
from my_thread import MyThread


class FFmpegRead(CameraBase):
    __gpu_pool = None
    def __init__(self, path, size, gpus=None, deal_max=5, logger=False, fps=None, time_rec=5):
        """
        初始化
        :param path:str;RTSP流地址
        :param size: list; [w, h], type=int; 视频尺寸，宽、高
        :param gpus:optional;list;each object is str,example "0";所有GPU的索引列表, None情况下则认为使用CPU
        :param logger:optional;bool or logging.Logger; 是否输出信息,输出方式print或logging.Logger
        :param deal_max: optional;int;慎重修改，影响内存占用。处理队列的最大值,0为不限制
        :param time_rec: (int); 每帧读流耗时的时间记录
        """
        CameraBase.__init__(self, size, logger)

        self.__path = path
        self.__gpus = gpus
        self.__fps = fps
        if FFmpegRead.__gpu_pool is None and self.__gpus is not None:
            FFmpegRead.__gpu_pool = list(self.__gpus).copy()

        self.__pipe = None
        self.__t = None
        self.__is_read = False
        self.__read_timeout = False
        self.__q = queue.Queue(maxsize=deal_max)
        self.__timeout = 5
        self.__total_timeout = 0
        self.__read_times = collections.deque(maxlen=time_rec)  # 读流时长记录,单位:帧


    def start_read(self):
        """开启读流"""
        self.__read_times.clear()
        if self.__is_read:
            self.pinfo("Camera has been open.Please not repeat to open.Path:{}".format(self.__path), 1)
            return self.__t
        if self.__t is not None and self.__t.is_alive():
            self.pinfo("Waiting old read process end.Path:{}".format(self.__path))
            self.__t.join()
        self.__is_read = True
        self.__t = MyThread(target=self.__receive)
        self.__t.start()
        return self.__t


    def close_read(self):
        """关闭读流"""
        if not self.__is_read:
            self.pinfo("Camera is not run, so you can't turn it off.Path:{}".format(self.__path), 1)
            return
        self.__is_read = False
        if self.__t.is_alive():
            self.__t.join()
        self.pinfo("Read the camera is closed.Path:{}".format(self.__path))


    def is_open(self):
        return self.__is_read


    def read(self):
        """
        获取当前帧图像
        :return: np.array; shape=(h,w,3), dtype=np.uint8; BGR图片
                None为摄像头未开启或读取超时
        """
        if not self.__is_read:
            self.pinfo("The camera is not opening.")
            return None
        try:
            image = self.__q.get(timeout=self.__timeout)
        except queue.Empty:
            self.__total_timeout += self.__timeout
            self.pinfo("Read the frame from queue more than {}s,Path:{}".format(
                self.__timeout, self.__path), 1)
            return None
        if self.__total_timeout != 0:
            self.pinfo("The deal queue is empty.Timeout:{},Path:{}".format(
                self.__total_timeout, self.__path))
            self.__total_timeout = 0
        return image


    def receive_deal(self, image):
        """
        读取到的每帧图像放入处理队列，保持最新的几帧图像
        :param image: np.array;shape=(h,w,3),dtype=np.uint8; BGR图片
        :return:
        """
        if self.__q.full():
            self.__q.get()
        self.__q.put(image)


    def clear_receive_cache(self):
        """清理读流导致的缓存"""
        self.__q.queue.clear()


    def get_receive_cache(self):
        """获取读流缓存图片的大小"""
        return self.__q.qsize()


    def get_read_times(self):
        """
        获取读流耗费的时长记录
        :return: (list); 长度与类定义的time_rec参数相关。
        """
        return list(self.__read_times)


    def clear_queue(self):
        """清空处理队列中的缓存图像,在len(self.__q)过大的时候使用,更新当前获取图像"""
        self.pinfo("Clear the deal queue, cache len:{}".format(self.__q.qsize()))
        self.__q.queue.clear()


    def __receive(self):
        """
        通过FFMPEG读取视频流
        其他方式的读流可修改该部分，保留self.receive_deal, self.clear_receive_cache
        """
        gpu_index = None
        if self.__gpus is not None:
            if len(FFmpegRead.__gpu_pool) == 0:
                FFmpegRead.__gpu_pool = list(self.__gpus).copy()
            gpu_index = FFmpegRead.__gpu_pool.pop()
            self.pinfo("Use GPU INDEX {}(Remain:{}) to read.Path:{}".format(gpu_index * 5, FFmpegRead.__gpu_pool, self.__path))
        command = [
            "./ffmpeg.exe", "-y",
            "-hwaccel_device", gpu_index,  # 指定使用某个GPU解码
            "-hwaccel", "nvdec",  # 指定使用nvdec硬件加速
            "-c:v", "h264_cuvid",  # GPU编码格式
            "-v", "8",  # 日志等级:fatal, Only show fatal errors.
            "-rtsp_transport", "tcp",
            "-vsync", "0",
            "-i", self.__path,
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-vf", "fps={}".format(self.__fps), # 设置帧数的过滤器（？是否可以通过输入端直接设置帧数）
            "-preset", "fast",  # this option only works with ffmpeg with GPU build
            "-id3v2_version", "3",
            "-"
        ]
        if self.__fps is None:
            del_command = ["-vf", "fps={}".format(self.__fps)]
            command = [c for c in command if c not in del_command]
        if gpu_index is None:
            del_command = [
                "-hwaccel_device", gpu_index,
                "-hwaccel", "nvdec",
                "-c:v", "h264_cuvid",
                "-preset", "fast"
            ]
            command = [c for c in command if c not in del_command]
        # 去除ffmpeg的弹窗
        startupinfo = sp.STARTUPINFO()
        startupinfo.dwFlags |= sp.STARTF_USESHOWWINDOW
        self.__pipe = sp.Popen(command, stdin=sp.PIPE, stdout=sp.PIPE, startupinfo=startupinfo)
        self.pinfo("Start the read rtsp subprocess.PID:{}, Path:{}".format(self.__pipe.pid, self.__path))
        loss_num = 0
        restart_num = 0
        if self.__is_read:
            st = time.time()
            # TODO 是否存在一种可能，poll()为正常，但是pipe.stdout.read()仍然读不到图像，或者会超时
            # 子进程（ffmpeg读流）未运行的话，重新启动
            # poll()返回该子进程的状态，0正常结束，1 sleep(子进程不存在)，-15 kill，None正在运行
            # 不能使用os.kill，因为子线程可能不存在
            if self.__pipe.poll() is not None:
                self.__pipe.terminate()
                self.__pipe.communicate()
                self.__pipe = sp.Popen(command, stdin=sp.PIPE, stdout=sp.PIPE)
                restart_num += 1
                time.sleep(restart_num + 3)
                if restart_num % 100 != 1:
                    pass
                info = "The popen of read ffmpeg not run.Restart num:{},Status:{},PID:{}," \
                       "Path:{}".format(restart_num, self.__pipe.poll(), self.__pipe.pid, self.__path)
                self.pinfo(info, level=1)
                pass
            if restart_num != 0:
                self.pinfo("Read subprocess restart successful.Num:{},PID:{},Path:{}".format(
                    restart_num, self.__pipe.pid, self.__path))
                restart_num = 0
            timer = threading.Timer(self.__timeout, self.__timeout_callback, [command])  # 定时关闭进程
            self.__read_timeout = False
            timer.start()
            frame_len = int(self.w * self.h * 3)
            x = self.__pipe.stdout.read(frame_len)
            timer.cancel()
            if self.__read_timeout:
                timer.join()
                time.sleep(1)
                pass
            elif len(x) != frame_len:
                if loss_num == 0:
                    self.pinfo("RSTP data miss,skip this frame.Path:{}".format(self.__path), 1)
                loss_num += 1
                pass
            elif loss_num != 0:
                self.pinfo("RSTP data back to normal.Miss num:{},Path:{}".format(
                    loss_num, self.__path))
                loss_num = 0
            bgr_image = np.frombuffer(x, dtype=np.uint8).reshape(self.h, self.w, 3)
            use_time = int((time.time() - st) * 1000)
            self.__read_times.append(use_time)
            # 获取到图片的后期处理
            self.receive_deal(bgr_image)
        self.pinfo("Read image by rstp has been end.Path:{}".format(self.__path))
        self.__pipe.terminate()  # 关闭popen
        self.__pipe.communicate()  # 等待子进程关闭
        if self.__gpus is not None:
            FFmpegRead.__gpu_pool.append(gpu_index)
            self.pinfo("Rtsp read is end, give back gpu index {} to pool.Pool:{}".format(
                gpu_index, FFmpegRead.__gpu_pool))

        self.clear_receive_cache()


    def __timeout_callback(self, ffmpeg_decode):
        """超时处理，强制关闭管道及相关进程"""
        self.pinfo("RTSP read more than {}s, kill the process.PID:{}, Path:{}".format(
            self.__timeout, self.__pipe.pid, self.__path), 2)
        try:
            self.__read_timeout = True
            sp.Popen("taskkill /F /T /PID " + str(self.__pipe.pid) , shell=True)
            # 不能使用self.__pipe.terminate()否则self.__pipe.stdout.read()会出现ValueError: read of closed file
            # os.killpg(self.__pipe.pid, signal.SIGKILL)
            # print(ffmpeg_decode)
            # self.__pipe = sp.Popen(ffmpeg_decode, stdin=sp.PIPE, stdout=sp.PIPE)
        except:
            self.pinfo("Kill the pipe about RTSP appear ERROR.PID:{},Path:{}".format(
                self.__pipe.pid, self.__path), 2)
            self.pinfo(traceback.format_exc(), 2)
        finally:
            self.pinfo("Finish timeout handling and restart rtsp.PID:{},Path:{}".format(
                self.__pipe.pid, self.__path))


