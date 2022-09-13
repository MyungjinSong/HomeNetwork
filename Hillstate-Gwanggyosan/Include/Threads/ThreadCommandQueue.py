import os
import sys
import time
import math
import queue
import threading
from typing import Union
CURPATH = os.path.dirname(os.path.abspath(__file__))
INCPATH = os.path.dirname(CURPATH)
sys.path.extend([CURPATH, INCPATH])
sys.path = list(set(sys.path))
del CURPATH, INCPATH
from Define import *
from Common import Callback, writeLog
from RS485 import PacketParser, RS485HwType


class ThreadCommandQueue(threading.Thread):
    _keepAlive: bool = True

    def __init__(self, queue_: queue.Queue):
        threading.Thread.__init__(self, name='Command Queue Thread')
        self._queue = queue_
        self._retry_cnt = 10
        self._delay_response = 0.4
        self.sig_terminated = Callback()

    def run(self):
        writeLog('Started', self)
        while self._keepAlive:
            if not self._queue.empty():
                elem = self._queue.get()
                elem_txt = '\n'
                for k, v in elem.items():
                    elem_txt += f'  {k}: {v}\n'
                writeLog(f'Get Command Queue: \n{{{elem_txt}}}', self)
                try:
                    dev = elem.get('device')
                    category = elem.get('category')
                    target = elem.get('target')
                    parser = elem.get('parser')
                    if target is None or parser is None:
                        continue

                    if isinstance(dev, Light):
                        if category == 'state':
                            self.set_state_common(dev, target, parser)
                    elif isinstance(dev, Outlet):
                        if category == 'state':
                            self.set_state_common(dev, target, parser)
                    elif isinstance(dev, GasValve):
                        if category == 'state':
                            if target == 0:
                                self.set_state_common(dev, target, parser)
                            else:  # 밸브 여는것은 지원되지 않음!
                                packet_query = dev.makePacketQueryState()
                                parser.sendPacket(packet_query)
                    elif isinstance(dev, Thermostat):
                        if category == 'state':
                            if target == 'OFF':
                                self.set_state_common(dev, 0, parser)
                            elif target == 'HEAT':
                                self.set_state_common(dev, 1, parser)
                        elif category == 'temperature':
                            self.set_temperature(dev, target, parser)
                    elif isinstance(dev, Ventilator):
                        if category == 'state':
                            self.set_state_common(dev, target, parser)
                        elif category == 'rotationspeed':
                            self.set_rotation_speed(dev, target, parser)
                    elif isinstance(dev, AirConditioner):
                        if category == 'active':
                            self.set_state_common(dev, target, parser)
                            if target:
                                self.set_airconditioner_mode(dev, 1, parser)  # 최초 가동 시 모드를 '냉방'으로 바꿔준다
                                # self.set_rotation_speed(dev, 1, parser)  # 최초 가동 시 풍량을 '자동'으로 바꿔준다
                        elif category == 'temperature':
                            self.set_temperature(dev, target, parser)
                        elif category == 'rotationspeed':
                            self.set_rotation_speed(dev, target, parser)
                    elif isinstance(dev, Elevator):
                        if category == 'state':
                            self.set_elevator_call(dev, target, parser)
                    elif isinstance(dev, SubPhone):
                        if category == 'doorcam':
                            self.set_doorcam_state(dev, target, parser)
                        elif category == 'doorlock':
                            self.set_doorlock_open(dev, target, parser)
                    """
                    elif isinstance(dev, DoorLock):
                        if category == 'state':
                            if target == 'Unsecured':
                                self.set_doorlock_open(dev, parser)
                    elif isinstance(dev, DoorPhone):
                        if category == 'cam_power':
                            self.set_doorphone_camera_power(dev, target, parser)
                    """
                except Exception as e:
                    writeLog(str(e), self)
            else:
                time.sleep(1e-3)
        writeLog('Terminated', self)
        self.sig_terminated.emit()

    def stop(self):
        self._keepAlive = False

    @staticmethod
    def getSendParams(parser: PacketParser) -> tuple:
        interval = 0.2
        retry_cnt = 10
        if parser.getRS485HwType() == RS485HwType.Socket:
            # ew11은 무선 송수신 레이턴시때문에 RS485 IDLE 시간을 명확하게 알 수 없으므로
            # 짧은 간격으로 패킷을 많이 쏴보도록 한다
            interval = 0.1
            retry_cnt = 50
        return interval, retry_cnt

    def set_state_common(self, dev: Device, target: int, parser: PacketParser):
        tm_start = time.perf_counter()
        cnt = 0
        packet_command = dev.makePacketSetState(bool(target))
        interval, retry_cnt = self.getSendParams(parser)
        while cnt < retry_cnt:
            if dev.state == target:
                break
            if parser.isRS485LineBusy():
                time.sleep(1e-3)  # prevent cpu occupation
                continue
            parser.sendPacket(packet_command)
            cnt += 1
            time.sleep(interval)  # wait for parsing response
        if cnt > 0:
            tm_elapsed = time.perf_counter() - tm_start
            writeLog('set_state_common::send # = {}, elapsed = {:g} msec'.format(cnt, tm_elapsed * 1000), self)
            time.sleep(self._delay_response)
        dev.publish_mqtt()

    def set_temperature(self, dev: Thermostat, target: float, parser: PacketParser):
        # 힐스테이트는 온도값 범위가 정수형이므로 올림처리해준다
        tm_start = time.perf_counter()
        cnt = 0
        target_temp = math.ceil(target)
        packet_command = dev.makePacketSetTemperature(target_temp)
        interval, retry_cnt = self.getSendParams(parser)
        while cnt < retry_cnt:
            if dev.temp_config == target_temp:
                break
            if parser.isRS485LineBusy():
                time.sleep(1e-3)  # prevent cpu occupation
                continue
            parser.sendPacket(packet_command)
            cnt += 1
            time.sleep(interval)  # wait for parsing response
        if cnt > 0:
            tm_elapsed = time.perf_counter() - tm_start
            writeLog('set_temperature::send # = {}, elapsed = {:g} msec'.format(cnt, tm_elapsed * 1000), self)
            time.sleep(self._delay_response)
        dev.publish_mqtt()

    def set_rotation_speed(self, dev: Union[Ventilator, AirConditioner], target: int, parser: PacketParser):
        tm_start = time.perf_counter()
        if isinstance(dev, Ventilator):
            # Speed 값 변환 (100단계의 풍량을 세단계로 나누어 1, 3, 7 중 하나로)
            if target <= 30:
                conv = 0x01
            elif target <= 60:
                conv = 0x03
            else:
                conv = 0x07
        else:
            # Speed 값 변환
            if target <= 25:
                conv = 0x01
            elif target <= 50:
                conv = 0x02
            elif target <= 75:
                conv = 0x03
            else:
                conv = 0x04
        cnt = 0
        packet_command = dev.makePacketSetRotationSpeed(conv)
        interval, retry_cnt = self.getSendParams(parser)
        while cnt < retry_cnt:
            if dev.rotation_speed == conv:
                break
            if parser.isRS485LineBusy():
                time.sleep(1e-3)  # prevent cpu occupation
                continue
            parser.sendPacket(packet_command)
            cnt += 1
            time.sleep(interval)  # wait for parsing response
        if cnt > 0:
            tm_elapsed = time.perf_counter() - tm_start
            writeLog('set_rotation_speed::send # = {}, elapsed = {:g} msec'.format(cnt, tm_elapsed * 1000), self)
            time.sleep(self._delay_response)
        dev.publish_mqtt()

    def set_airconditioner_mode(self, dev: AirConditioner, target: int, parser: PacketParser):
        tm_start = time.perf_counter()
        cnt = 0
        packet_command = dev.makePacketSetMode(target)
        interval, retry_cnt = self.getSendParams(parser)
        while cnt < retry_cnt:
            if dev.mode == target:
                break
            if parser.isRS485LineBusy():
                time.sleep(1e-3)  # prevent cpu occupation
                continue
            parser.sendPacket(packet_command)
            cnt += 1
            time.sleep(interval)  # wait for parsing response
        if cnt > 0:
            tm_elapsed = time.perf_counter() - tm_start
            writeLog('set_airconditioner_mode::send # = {}, elapsed = {:g} msec'.format(cnt, tm_elapsed * 1000), self)
            time.sleep(self._delay_response)
        dev.publish_mqtt()
    
    def set_elevator_call(self, dev: Elevator, target: int, parser: PacketParser):
        tm_start = time.perf_counter()
        cnt = 0
        if target == 5:
            packet_command = dev.makePacketCallUpside()
        elif target == 6:
            packet_command = dev.makePacketCallDownside()
        else:
            return
        interval, retry_cnt = self.getSendParams(parser)
        while cnt < retry_cnt:
            if dev.state == target:
                break
            if parser.isRS485LineBusy():
                time.sleep(1e-3)  # prevent cpu occupation
                continue
            parser.sendPacket(packet_command)
            cnt += 1
            time.sleep(interval)  # wait for parsing response
        if cnt > 0:
            tm_elapsed = time.perf_counter() - tm_start
            writeLog('set_elevator_call({})::send # = {}, elapsed = {:g} msec'.format(target, cnt, tm_elapsed * 1000), self)
            time.sleep(self._delay_response)
        dev.publish_mqtt()

    def set_doorcam_state(self, dev: SubPhone, target: int, parser: PacketParser):
        packet = dev.makePacketSetDoorCamState(target)
        parser.sendPacket(packet)

    def set_doorlock_open(self, dev: SubPhone, target: int, parser: PacketParser):
        # TODO:
        if target == 1:
            if dev.state_door_cam:
                if dev.state_outer_door_call:
                    parser.sendPacket(dev.makePacketOpenOuterDoor())
                else:
                    parser.sendPacket(dev.makePacketOpenDoorLock())
            else:
                parser.sendPacket(dev.makePacketSetDoorCamState(1))
                parser.sendPacket(dev.makePacketOpenDoorLock())
            parser.sendPacket(dev.makePacketSetDoorCamState(0))
        else:
            pass  # do nothing?

    """
    def set_doorlock_open(self, dev: DoorLock, parser: PacketParser):
        dev.open()  # GPIO
        packet_command = dev.makePacketOpen()
        parser.sendPacket(packet_command)
        time.sleep(0.3)
        parser.sendPacket(packet_command)
        time.sleep(0.3)

    def set_doorphone_camera_power(self, dev: DoorPhone, target: int, parser: PacketParser):
        if target:
            dev.turn_on_camera()
        else:
            dev.turn_off_camera()
    """
