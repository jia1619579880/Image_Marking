#############################################################################################
##### 摄像头基类(一些通用属性)
#############################################################################################
import logging
class CameraBase:

    def __init__(self, size, logger):
        self.w, self.h = size
        self.logger = logger

    def pinfo(self, value, level=0):
        """
        输出日志信息
        :param value: str; 输出内容
        :param level: int; 内容等级[0:信息,1:警告,2:错误]
        :return:
        """
        if isinstance(self.logger, bool):
            if self.logger:
                print(value)
        else:
            assert isinstance(self.logger, logging.Logger)
            if level == 0:
                self.logger.info(value)
            elif level == 1:
                self.logger.warning(value)
            else:
                self.logger.error(value)