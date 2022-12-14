import os
import sys
import json
import hmac
import base64
import random
import hashlib
import datetime
from regex import E
import requests
import email.utils
import urllib.parse
from OpenSSL import crypto
from typing import Union, List
import paho.mqtt.client as mqtt
CURPATH = os.path.dirname(os.path.abspath(__file__))  # {$PROJECT}/Include/ThinQ
INCPATH = os.path.dirname(CURPATH)  # {$PROJECT}/Include/
sys.path.extend([CURPATH, INCPATH])
sys.path = list(set(sys.path))
del INCPATH
from Common import writeLog, Callback


class ThinQ:
    client_id: Union[str, None] = None
    user_no: Union[str, None] = None
    access_token: Union[str, None] = None

    country_code: str = 'KR'
    language_code: str = 'ko-KR'
    api_key: str = ''
    api_client_id: str = ''
    refresh_token: str = ''
    oauth_secret_key: str = ''
    app_client_id: str = ''
    app_key: str = ''

    uri_thinq1: Union[str, None] = None
    uri_thinq2: Union[str, None] = None
    uri_oauth: Union[str, None] = None

    subscribe_topics: List[str]
    mqtt_client: mqtt.Client = None
    log_mqtt_message: bool = False
    
    device_discover_list: List[dict]
    robot_cleaner_dev_id: str = ''
    mqtt_topic: str = ''

    def __init__(self, **kwargs):
        self.sig_publish_mqtt = Callback(str, dict)
        
        self.subscribe_topics = list()
        self.device_discover_list = list()
        if 'country_code' in kwargs.keys():
            self.country_code = kwargs.get('country_code')
        if 'language_code' in kwargs.keys():
            self.language_code = kwargs.get('language_code')
        if 'api_key' in kwargs.keys():
            self.api_key = kwargs.get('api_key')
        if 'api_client_id' in kwargs.keys():
            self.api_client_id = kwargs.get('api_client_id')
        if 'refresh_token' in kwargs.keys():
            self.refresh_token = kwargs.get('refresh_token')
        if 'oauth_secret_key' in kwargs.keys():
            self.oauth_secret_key = kwargs.get('oauth_secret_key')
        if 'app_client_id' in kwargs.keys():
            self.app_client_id = kwargs.get('app_client_id')
        if 'app_key' in kwargs.keys():
            self.app_key = kwargs.get('app_key')
        if 'robot_cleaner_dev_id' in kwargs.keys():
            self.robot_cleaner_dev_id = kwargs.get('robot_cleaner_dev_id')
        if 'mqtt_topic' in kwargs.keys():
            self.mqtt_topic = kwargs.get('mqtt_topic')
        if 'log_mqtt_message' in kwargs.keys():
            self.log_mqtt_message = kwargs.get('log_mqtt_message')
        self.generate_rsa_csr_pemfiles()
        self.get_aws_root_ca_pem()

    def start(self):
        if not self.query_thinq_uris():
            return
        if not self.query_oauth_uris():
            return
        if not self.query_access_token():
            return
        if not self.query_user_number():
            return
        if not self.query_home_device_list():
            return
        if not self.get_certificate_from_server():
            return
        if not self.connect_mqtt_broker():
            return

    def stop(self):
        if self.mqtt_client is not None:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
            del self.mqtt_client
            self.mqtt_client = None

    def restart(self):
        self.stop()
        self.start()

    def release(self):
        self.stop()
        self.client_id = None
        self.user_no = None
        self.access_token = None
        self.uri_thinq1 = None
        self.uri_thinq2 = None
        self.uri_oauth = None

    @staticmethod
    def generate_random_string(length: int) -> str:
        characters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        result = ''
        for i in range(length):
            result += characters[random.randint(0, len(characters) - 1)]
        return result

    @staticmethod
    def generate_signature(message: str, key: str) -> str:
        hmac_obj = hmac.new(key.encode(encoding='utf-8'), message.encode(encoding='utf-8'), hashlib.sha1)
        hashed = hmac_obj.digest()
        b64_encoded = base64.b64encode(hashed)
        return b64_encoded.decode(encoding='utf-8')

    def generate_default_header(self) -> dict:
        headers = {
            'x-api-key': self.api_key,
            'x-thinq-app-ver': '3.6.1200',
            'x-thinq-app-type': 'NUTS',
            'x-thinq-app-level': 'PRD',
            'x-thinq-app-os': 'ANDROID',
            'x-thinq-app-logintype': 'LGE',
            'x-service-code': 'SVC202',
            'x-country-code': self.country_code,
            'x-language-code': self.language_code,
            'x-service-phase': 'OP',
            'x-origin': 'app-native',
            'x-model-name': 'samsung/SM-G930L',
            'x-os-version': 'AOS/7.1.2',
            'x-app-version': 'LG ThinQ/3.6.12110',
            'x-message-id': self.generate_random_string(22),
            'user-agent': 'okhttp/3.14.9'
        }
        
        headers['x-client-id'] = self.api_client_id if self.client_id is None else self.client_id
        if self.user_no is not None:
            headers['x-user-no'] = self.user_no
        if self.access_token is not None:
            headers['x-emp-token'] = self.access_token
        return headers
    
    def query_thinq_uris(self) -> bool:
        result: bool
        url = "https://route.lgthinq.com:46030/v1/service/application/gateway-uri"
        response = requests.get(url, headers=self.generate_default_header())
        if response.status_code == 200:
            response_json = json.loads(response.text)
            result = response_json.get('result')
            self.uri_thinq1 = result.get('thinq1Uri')
            self.uri_thinq2 = result.get('thinq2Uri')
            elapsed = response.elapsed.microseconds
            writeLog('query thinq uri success ({:g} msec)'.format(elapsed / 1000), self)
            result = True
        else:
            writeLog(f'failed to query thinq uri ({response.status_code}, {response.text})', self)
            result = False
        return result
    
    def query_oauth_uris(self) -> bool:
        result: bool
        if self.uri_thinq1 is None:
            writeLog(f'thinq uri is not queried yet!', self)
            return False
        
        url = self.uri_thinq1 + '/common/gatewayUriList'
        headers = {
            'Accept': 'application/json',
            'x-thinq-application-key': 'wideq',
            'x-thinq-security-key': 'nuts_securitykey'
        } 
        data = {
            'lgedmRoot': {
                'countryCode': self.country_code, 
                'langCode': self.language_code
            }
        }
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            response_json = json.loads(response.text)
            lgemdRoot = response_json.get('lgedmRoot')
            self.uri_oauth = lgemdRoot.get('oauthUri')
            elapsed = response.elapsed.microseconds
            writeLog('query oauth uri success ({:g} msec)'.format(elapsed / 1000), self)
            result = True
        else:
            writeLog(f'failed to query oauth uri ({response.status_code}, {response.text})', self)
            result = False
        return result

    def query_access_token(self) -> bool:
        result: bool
        if self.uri_oauth is None:
            writeLog(f'oauth uri is not queried yet!', self)
            return False
        
        url = self.uri_oauth + '/oauth/1.0/oauth2/token'
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token
        }
        requestUrl = '/oauth/1.0/oauth2/token' + '?' + urllib.parse.urlencode(data)
        now = datetime.datetime.utcnow()
        timestamp = email.utils.format_datetime(now)
        signature = self.generate_signature(f"{requestUrl}\n{timestamp}", self.oauth_secret_key)
        headers = {
            'x-lge-app-os': 'ADR',
            'x-lge-appkey': self.app_client_id,
            'x-lge-oauth-signature': signature,
            'x-lge-oauth-date': timestamp,
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        response = requests.post(url, params=data, headers=headers)
        if response.status_code == 200:
            response_json = json.loads(response.text)
            self.access_token = response_json.get('access_token')
            # expires_in_ = int(response_json.get('expires_in'))
            elapsed = response.elapsed.microseconds
            writeLog('query access token success ({:g} msec)'.format(elapsed / 1000), self)
            result = True
        else:
            writeLog(f'failed to query access token ({response.status_code}, {response.text})', self)
            result = False
        return result

    def query_user_number(self) -> bool:
        result: bool
        if self.access_token is None:
            writeLog(f'access token is not queried yet!', self)
            return False
        
        url = self.uri_oauth + '/users/profile'
        now = datetime.datetime.utcnow()
        timestamp = email.utils.format_datetime(now)
        signature = self.generate_signature(f"/users/profile\n{timestamp}", self.oauth_secret_key)
        headers = {
            'Accept': 'application/json',
            'Authorization': 'Bearer ' + self.access_token,
            'X-Lge-Svccode': 'SVC202',
            'X-Application-Key': self.app_key,
            'lgemp-x-app-key': self.app_client_id,
            'X-Device-Type': 'M01',
            'X-Device-Platform': 'ADR',
            'x-lge-oauth-date': timestamp,
            'x-lge-oauth-signature': signature
        }
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            response_json = json.loads(response.text)
            account = response_json.get('account')
            self.user_no = account.get('userNo')
            elapsed = response.elapsed.microseconds
            writeLog('query user number success ({:g} msec)'.format(elapsed / 1000), self)
            # create client id
            obj_hash = hashlib.sha256()
            now = int(datetime.datetime.now().timestamp())
            obj_hash.update((self.user_no + f'{now}').encode(encoding='utf-8'))
            self.client_id = obj_hash.hexdigest()
            result = True
        else:
            writeLog(f'failed to query user number ({response.status_code}, {response.text})', self)
            result = False
        return result

    def query_home_device_list(self) -> bool:
        result: bool
        if self.uri_thinq2 is None:
            writeLog(f'thinq uri is not queried yet!', self)
            return False
        
        url = self.uri_thinq2 + '/service/homes'
        response = requests.get(url, headers=self.generate_default_header())
        if response.status_code == 200:
            response_json = json.loads(response.text)
            result = response_json.get('result')
            home_list = result.get('item')
            self.device_discover_list.clear()
            for obj in home_list:
                homeId = obj.get('homeId')
                url2 = self.uri_thinq2 + '/service/homes/' + homeId
                response = requests.get(url2, headers=self.generate_default_header())
                if response.status_code == 200:
                    response_json = json.loads(response.text)
                    result = response_json.get('result')
                    devices = result.get('devices')
                    self.device_discover_list.extend(devices)
            self.print_device_discover_list()
            result = True
        else:
            writeLog(f'failed to query home - device list ({response.status_code}, {response.text})', self)
            result = False
        return result

    def print_device_discover_list(self):
        writeLog(f'discovered {len(self.device_discover_list)} device(s)', self)
        for device in self.device_discover_list:
            dev_id = device.get('deviceId')
            dev_type = device.get('deviceType')
            modelName = device.get('modelName')
            alias = device.get('alias')
            writeLog(f'{alias}::{modelName}::{dev_type}::{dev_id}', self)

    def generate_rsa_csr_pemfiles(self):
        pubkey_pem_path = os.path.join(CURPATH, 'pubkey.pem')
        privkey_pem_path = os.path.join(CURPATH, 'privkey.pem')
        csr_pem_path = os.path.join(CURPATH, 'csr.pem')
        if not os.path.isfile(pubkey_pem_path) or not os.path.isfile(privkey_pem_path) or not os.path.isfile(csr_pem_path):
            keypair = crypto.PKey()
            keypair.generate_key(crypto.TYPE_RSA, 2048)
            pubkey_pem = crypto.dump_publickey(crypto.FILETYPE_PEM, keypair).decode(encoding='utf-8')
            with open(pubkey_pem_path, 'w') as fp:
                fp.write(pubkey_pem)
            privkey_pem = crypto.dump_privatekey(crypto.FILETYPE_PEM, keypair).decode(encoding='utf-8')
            with open(privkey_pem_path, 'w') as fp:
                fp.write(privkey_pem)
            
            req = crypto.X509Req()
            req.get_subject().CN = "AWS IoT Certificate"
            req.get_subject().O = "Amazon"
            req.set_pubkey(keypair)
            req.sign(keypair, "sha256")
            csr_pem = crypto.dump_certificate_request(crypto.FILETYPE_PEM, req).decode(encoding='utf-8')
            with open(csr_pem_path, 'w') as fp:
                fp.write(csr_pem)

    def get_certificate_from_server(self) -> bool:
        result: bool
        if self.uri_thinq2 is None:
            writeLog(f'thinq uri is not queried yet!', self)
            return False

        csr_pem_path = os.path.join(CURPATH, 'csr.pem')
        if not os.path.isfile(csr_pem_path):
            writeLog(f'cannot find csr pem file', self)
            return False

        url = self.uri_thinq2 + '/service/users/client'
        response = requests.post(url, headers=self.generate_default_header())
        if response.status_code == 200:
            with open(csr_pem_path, 'r') as fp:
                csr_pem = fp.read()
            url = self.uri_thinq2 + '/service/users/client/certificate'
            csr_pem = csr_pem.replace('-----BEGIN CERTIFICATE REQUEST-----', '')
            csr_pem = csr_pem.replace('-----END CERTIFICATE REQUEST-----', '')
            csr_pem = csr_pem.replace('\r\n', '')
            data = {
                'csr': csr_pem
            }
            response = requests.post(url, json=data, headers=self.generate_default_header())
            if response.status_code == 200:
                response_json = json.loads(response.text)
                result = response_json.get('result')
                certificate_pem = result.get('certificatePem')
                cert_pem_path = os.path.join(CURPATH, 'aws_cert.pem')
                with open(cert_pem_path, 'w') as fp:
                    fp.write(certificate_pem)
                self.subscribe_topics.clear()
                subscriptions = result.get('subscriptions')  # 구독할 Topic
                self.subscribe_topics.extend(subscriptions)
                elapsed = response.elapsed.microseconds
                writeLog('query certificate success ({:g} msec)'.format(elapsed / 1000), self)
                result = True
            else:
                writeLog(f'failed to query certificate ({response.status_code}, {response.text})', self)
                result = False
        else:
            writeLog(f'failed to visit service ({response.status_code}, {response.text})', self)
            result = False
        return result

    def get_aws_root_ca_pem(self) -> bool:
        result: bool
        rootca_pem_path = os.path.join(CURPATH, 'aws_root_ca.pem')
        if os.path.isfile(rootca_pem_path):
            return True

        url = 'https://www.amazontrust.com/repository/AmazonRootCA1.pem'
        response = requests.get(url)
        if response.status_code == 200:
            rootca_pem = response.text
            with open(rootca_pem_path, 'w') as fp:
                fp.write(rootca_pem)
            elapsed = response.elapsed.microseconds
            writeLog('query root CA from AWS ({:g} msec)'.format(elapsed / 1000), self)
            result = True
        else:
            writeLog(f'failed to query root CA from AWS ({response.status_code}, {response.text})', self)
            result = False
        return result

    def connect_mqtt_broker(self) -> bool:
        if self.client_id is None:
            writeLog(f'client id is not generated yet!', self)
            return False
        
        rootca_pem_path = os.path.join(CURPATH, 'aws_root_ca.pem')
        if not os.path.isfile(rootca_pem_path):
            writeLog('cannot find aws root ca pem file', self)
            return False
        cert_pem_path = os.path.join(CURPATH, 'aws_cert.pem')
        if not os.path.isfile(cert_pem_path):
            writeLog('cannot find aws cert pem file', self)
            return False
        privkey_pem_path = os.path.join(CURPATH, 'privkey.pem')
        if not os.path.isfile(privkey_pem_path):
            writeLog('cannot find private key pem file', self)
            return False
        
        # get mqtt broker host address
        url = "https://common.lgthinq.com/route"
        response = requests.get(url, headers=self.generate_default_header())
        mqttserver = ''
        if response.status_code == 200:
            response_json = json.loads(response.text)
            result = response_json.get('result')
            mqttserver = result.get('mqttServer')
        else:
            return False

        idx = mqttserver.rfind(':')
        mqtt_host = mqttserver[:idx]
        mqtt_port = int(mqttserver[idx+1:])
        self.mqtt_client = mqtt.Client(client_id=self.client_id)
        self.mqtt_client.on_connect = self.onMqttClientConnect
        self.mqtt_client.on_disconnect = self.onMqttClientDisconnect
        self.mqtt_client.on_message = self.onMqttClientMessage
        self.mqtt_client.on_subscribe = self.onMqttClientSubscribe

        self.mqtt_client.tls_set(ca_certs=rootca_pem_path, certfile=cert_pem_path, keyfile=privkey_pem_path)
        self.mqtt_client.connect(host=mqtt_host[6:], port=mqtt_port)
        self.mqtt_client.loop_start()

    def onMqttClientConnect(self, _, userdata, flags, rc):
        writeLog('connected to aws iot core (mqtt broker): {}, {}, {}'.format(userdata, flags, rc), self)
        for topic in self.subscribe_topics:
            self.mqtt_client.subscribe(topic)

    def onMqttClientDisconnect(self, _, userdata, rc):
        writeLog('disconnected from aws iot core (mqtt broker): {}, {}'.format(userdata, rc), self)

    def onMqttClientSubscribe(self, _, userdata, mid, granted_qos):
        writeLog('mqtt subscribe: {}, {}, {}'.format(userdata, mid, granted_qos), self)

    def onMqttClientMessage(self, _, userdata, message):
        msg_dict = json.loads(message.payload.decode("utf-8"))
        if self.log_mqtt_message:
            writeLog('{}'.format(msg_dict), self)
        
        data = msg_dict.get('data')
        deviceId = msg_dict.get('deviceId')
        msg_type = msg_dict.get('type')
        if data is not None and deviceId is not None and msg_type is not None:
            if deviceId == self.robot_cleaner_dev_id:
                try:
                    state = data.get('state')
                    reported = state.get('reported')
                    robot_state = reported.get('ROBOT_STATE')
                    if robot_state is not None:
                        # possible state: 'SLEEP', 'CHARGING', 'INITAILIZING', 'CLEAN_SELECT', 'HOMING', 'CLEAN_EDGE', 
                        # 'PAUSE_EDGE', 'HOMING_PAUSE', 'PAUSE_SELECT' ...,
                        # {'EMERGENCY': 'ROBOT_LIFT', 'ROBOT_STUCK'}
                        writeLog(f'Robot Cleaner Current State: {robot_state}', self)
                        topic = self.mqtt_topic + '/robotcleaner/state'
                        if 'CLEAN' in robot_state or robot_state in ['INITAILIZING', 'HOMING']:
                            cleaning = 1
                        else:
                            cleaning = 0
                        message = {'cleaning': cleaning}
                        self.sig_publish_mqtt.emit(topic, message)
                except Exception:
                    pass

    def setEnableLogMqttMessage(self, enable: bool):
        self.log_mqtt_message = enable
