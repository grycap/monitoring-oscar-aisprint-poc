# Copyright (C) GRyCAP - I3M - UPV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import logging
import os
import uuid
import distutils.util
from datetime import datetime
from faassupervisor.events import parse_event
from faassupervisor.storage.config import StorageConfig, create_provider
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from yaml import parse

INFLUXDB_MEASUREMENT='aisprint_times'
# Config logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('MONITORING-AISPRINT')


def get_input_name(stg_config, parsed_event):
    input = stg_config.input[0]['path'].strip(' /')
    # Remove the bucket from input path
    input_path = ''
    input_path_list = input.split('/', 1)
    if len(input_path_list) == 2:
        input_path = input_path_list[1]
    key = parsed_event.object_key.strip(' /')
    input_name = key.removeprefix(input_path)
    return input_name.strip(' /')


def write_times(monitoring_mode, parsed_event, input_name):
    # Read InfluxDB environment variables
    url = os.environ.get('INFLUXDB_URL')
    token = os.environ.get('INFLUXDB_TOKEN')
    org = os.environ.get('INFLUXDB_ORG')
    bucket = os.environ.get('INFLUXDB_BUCKET')
    service_name = os.environ.get('SERVICE_NAME')
    verify_ssl = bool(distutils.util.strtobool(os.environ.get('INFLUXDB_SSL_VERIFY', 'True')))
    # Create client
    influx_client = InfluxDBClient(url=url, token=token, org=org, verify_ssl=verify_ssl)
    logger.info(f'Writing times to InfluxDB ({url}) bucket \"{bucket}\"...')
    # Get event timestamp
    timestamp = string_time_to_timestamp(parsed_event.event_time)
    # Field to write
    field = 'start_time' if monitoring_mode == 'input' else 'end_time'
    # Prepare InfluxDB point
    p =  Point(INFLUXDB_MEASUREMENT).tag('file_name', input_name).tag('service_name', service_name).field(field, timestamp)
    # Write the point
    write_api = influx_client.write_api(write_options=SYNCHRONOUS)
    write_api.write(bucket=bucket, record=p)
    logger.info(f'Value \"{timestamp}\" successfully written in field \"{field}\"')



def is_tracked(input_name):
    return input_name.startswith('aisprint-')


def string_time_to_timestamp(string_time):
    return datetime.strptime(string_time, '%Y-%m-%dT%H:%M:%S.%fZ').timestamp()


def generate_tracking_name(input_name):
    # Get file extension
    ext_list = input_name.rsplit('.', 1)
    ext = ''
    if len(ext_list) == 2:
        ext = '.' + ext_list[1]
    # Generate random UUID
    random_uuid = str(uuid.uuid4())
    # Return the tracking name
    tracking_name = 'aisprint-' + random_uuid + ext
    return tracking_name


def copy_to_output(parsed_event, stg_config, input_name):
    # Check if output is defined
    if len(stg_config.output) > 0:
        # Create s3 client
        auth_data = stg_config._get_input_auth_data(parsed_event)
        stg_provider = create_provider(auth_data)
        s3_client = stg_provider.client
        provider_type = stg_provider._TYPE.lower()
        for out in stg_config.output:
            # Only copy files in the same storage provider (the default for the service/function)
            if out['storage_provider'] == provider_type or out['storage_provider'] == provider_type + '.default':
                split_path = out['path'].split('/', 1)
                bucket  = split_path[0]
                key = input_name
                if len(split_path) == 2:
                    key = f'{split_path[1]}/{input_name}'
                # Copy the file
                source = {
                    'Bucket': parsed_event.bucket_name,
                    'Key': parsed_event.object_key
                }
                s3_client.copy(source, bucket, key)
                logger.info(f'File \"{parsed_event.object_key}\" from bucket \"{parsed_event.bucket_name}\" copied to bucket \"{bucket}\" with key \"{key}\"')


def start_monitoring():
    monitoring_mode = os.environ.get('MONITORING_MODE', '').lower()
    if monitoring_mode != 'input' and monitoring_mode != 'output':
        logger.error('The \"MONITORING_MODE\" environment variable must be set as \"input\" or \"output\"')
        return
    else:
        # Parse the event from the 'EVENT' environment variable
        event = os.environ.get('EVENT', '')
        logger.info(f'Parsing event:\n{event}')
        parsed_event = parse_event(event)
        # Parse the storage config
        stg_config = StorageConfig()
        # Get the input file name (including subfolders)
        input_name = get_input_name(stg_config, parsed_event)
        logger.info(f'Processing file \"{input_name}\"...')
        # If MONITORING_MODE=input check if input_name is tracked and generate tracking name if not
        if monitoring_mode == 'input' and not is_tracked(input_name):
            input_name = generate_tracking_name(input_name)
            logger.info(f'Generated tracking name \"{input_name}\"')
        # Copy event file to defined output (only in the "default" provider)
        copy_to_output(parsed_event, stg_config, input_name)
        # Send times to InfluxDB
        write_times(monitoring_mode, parsed_event, input_name)


if __name__ == '__main__':
    start_monitoring()
