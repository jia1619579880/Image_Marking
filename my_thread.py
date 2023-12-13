################################################################
##### 线程改进：获取报错信息
################################################################
import threading
class MyThread(threading.Thread):

    def __init__(self, *args, **kwargs):
        """
        初始化
        :param args: 位置参数
        :param kwargs: 关键字参数
        """
        super(MyThread, self).__init__(*args, **kwargs)
        self.__execute_res = None
        self.__exception = None


    def run(self):
        try:
            self.__execute_res = self._target(*self._args, **self._kwargs)
        except BaseException as exc:
            self.__exception = exc


    def get_execute_res(self, timeout=None):
        """
        获取函数执行完成后返回的结果
        :return:
        """
        if timeout is None:
            self.join()
        else:
            self.join(timeout=timeout)
        if self.__exception:
            raise self.__exception
        else:
            return self.__execute_res

