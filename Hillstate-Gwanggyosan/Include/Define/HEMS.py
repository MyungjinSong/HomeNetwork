import json
import datetime
from Device import *
from Common import HEMSDevType, HEMSCategory


class HEMS(Device):
    data: dict

    def __init__(self, name: str = 'HEMS', index: int = 0, room_index: int = 0):
        super().__init__(name, index, room_index)
        self.dev_type = DeviceType.HEMS
        self.mqtt_publish_topic = f'home/state/hems/{self.room_index}/{self.index}'
        self.mqtt_subscribe_topic = f'home/command/hems/{self.room_index}/{self.index}'
        self.data = dict()
    
    def setDefaultName(self):
        self.name = 'HEMS'

    def publishMQTT(self):
        pass

    def updateState(self, _: int, **kwargs):
        if 'monitor_data' in kwargs.keys():
            monitor_data = kwargs.get('monitor_data')
            self.data['last_recv_time'] = datetime.datetime.now()
            for key in list(monitor_data.keys()):
                self.data[key] = monitor_data.get(key)
                if key in ['electricity_current']:
                    topic = self.mqtt_publish_topic + f'/{key}'
                    value = monitor_data.get(key)
                    """
                    if value == 0:
                        writeLog(f"zero power consumption? >> {prettifyPacket(monitor_data.get('packet'))}", self)
                    """
                    obj = {"value": value}
                    if self.mqtt_client is not None:
                        self.mqtt_client.publish(topic, json.dumps(obj), 1)

    def makePacketQuery(self, devtype: HEMSDevType, category: HEMSCategory) -> bytearray:
        command = ((devtype.value & 0x0F) << 4) | (category.value & 0x0F)
        return bytearray([0x7F, 0xE0, command, 0x00, 0xEE])
