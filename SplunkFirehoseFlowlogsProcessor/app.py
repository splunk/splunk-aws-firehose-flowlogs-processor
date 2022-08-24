# Copyright 2014, Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Amazon Software License (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
#  http://aws.amazon.com/asl/
#
# or in the "license" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied. See the License for the specific language governing
# permissions and limitations under the License.

"""
For processing VPF FlowLogs data sent directly to firehose.

Flow Logs data sent to Firehose look like this:

{'invocationId': '827b170e-77e5-4627-bfb4-dd48e308a997', 
'deliveryStreamArn': 'arn:aws:firehose:us-east-1:647604195155:deliverystream/VPCFlowLogs-DirectKDF', 'region': 'us-east-1', 'records': 
[
    {'recordId': '49626154501644110739257545332878746850728803363251552258000000', 'approximateArrivalTimestamp': 1643160814345, 
    'data': 'eyJtZXNzYWdlIjoiMiA2NDc2MDQxOTUxNTUgZW5pLTA1ZmRkNTgzMTdhM2E1OGU0IDEwLjMwLjIuMjM4IDEwLjMwLjEuMjE3IDgwODkgMzkwMTYgNiAyMiAxMDUyNyAxNjQzMTYwNzMyIDE2NDMxNjA3OTIgQUNDRVBUIE9LIn0='}, 
    {'recordId': '49626154501644110739257545332878746850728803363251552258000001', 'approximateArrivalTimestamp': 1643160814345, 
    'data': 'eyJtZXNzYWdlIjoiMiA2NDc2MDQxOTUxNTUgZW5pLTA1ZmRkNTgzMTdhM2E1OGU0IDUyLjk0LjIyOC4xNzggMTAuMzAuMi4yMzggNDQzIDM3Mzc4IDYgMjQgNzIxMSAxNjQzMTYwNzMyIDE2NDMxNjA3OTIgQUNDRVBUIE9LIn0='}, 
    {'recordId': '49626154501644110739257545332878746850728803363251552258000002', 'approximateArrivalTimestamp': 1643160814345, 
    'data': 'eyJtZXNzYWdlIjoiMiA2NDc2MDQxOTUxNTUgZW5pLTA1ZmRkNTgzMTdhM2E1OGU0IDEwLjMwLjIuMjM4IDUyLjk0LjIyOC4xNzggMzczNzggNDQzIDYgMjMgNTEyNSAxNjQzMTYwNzMyIDE2NDMxNjA3OTIgQUNDRVBUIE9LIn0='}, 
    {'recordId': '49626154501644110739257545332878746850728803363251552258000003', 'approximateArrivalTimestamp': 1643160814345, 'data':
....
....
    '49626154501644110739257545332917432476956475551291277314000048', 'approximateArrivalTimestamp': 1643160874015, 
    'data': 'eyJtZXNzYWdlIjoiMiA2NDc2MDQxOTUxNTUgZW5pLTAyYjlkNDU5NTY3ZjYzYzliIDEwLjMwLjEuMjE3IDEwLjMwLjEuNjEgMzYyNzggODA4OSA2IDM0IDUyODUgMTY0MzE2MDc3OSAxNjQzMTYwODEwIEFDQ0VQVCBPSyJ9'}
    ]
}


The code below will:
1) Read the records from the event data
2) Decode the from base64 format
3) Read the message data which is the actual flow log records
4) Add line separator
5) Any individual record exceeding 6,000,000 bytes in size after decompression and encoding is marked as
   ProcessingFailed within the function. The original compressed record will be backed up to the S3 bucket
   configured on the Firehose.
7) Any additional records which exceed 6MB will be re-ingested back into Firehose.
7) The retry count for intermittent failures during re-ingestion is set 20 attempts. If you wish to retry fewer number
   of times for intermittent failures you can lower this value.
"""

import base64
import json
import boto3


def transformLogEvent(log_event):
    """Transform each log event.

    The default implementation below just extracts the message and appends a newline to it.

    Args:
    log_event (dict): The original log event. Structure is {"id": str, "timestamp": long, "message": str}

    Returns:
    str: The transformed log event.
    """
    return log_event['message'] + '\n'


def processRecords(records):
    for r in records:
        recId = r['recordId']
        data = base64.b64decode(r['data'])
        data = json.loads(data.decode('utf8'))
        joinedData = ''.join(transformLogEvent(data))
        dataBytes = joinedData.encode("utf-8")
        encodedData = base64.b64encode(dataBytes)
        yield {
            'data': encodedData,
            'result': 'Ok',
            'recordId': recId
        }

def putRecordsToFirehoseStream(streamName, records, client, attemptsMade, maxAttempts):
    failedRecords = []
    codes = []
    errMsg = ''
    # if put_record_batch throws for whatever reason, response['xx'] will error out, adding a check for a valid
    # response will prevent this
    response = None
    try:
        response = client.put_record_batch(DeliveryStreamName=streamName, Records=records)
    except Exception as e:
        failedRecords = records
        errMsg = str(e)

    # if there are no failedRecords (put_record_batch succeeded), iterate over the response to gather results
    if not failedRecords and response and response['FailedPutCount'] > 0:
        for idx, res in enumerate(response['RequestResponses']):
            # (if the result does not have a key 'ErrorCode' OR if it does and is empty) => we do not need to re-ingest
            if 'ErrorCode' not in res or not res['ErrorCode']:
                continue

            codes.append(res['ErrorCode'])
            failedRecords.append(records[idx])

        errMsg = 'Individual error codes: ' + ','.join(codes)

    if len(failedRecords) > 0:
        if attemptsMade + 1 < maxAttempts:
            print('Some records failed while calling PutRecordBatch to Firehose stream, retrying. %s' % (errMsg))
            putRecordsToFirehoseStream(streamName, failedRecords, client, attemptsMade + 1, maxAttempts)
        else:
            raise RuntimeError('Could not put records after %s attempts. %s' % (str(maxAttempts), errMsg))

def createReingestionRecord(originalRecord):
    return {'data': base64.b64decode(originalRecord['data'])}


def getReingestionRecord(reIngestionRecord):
    return {'Data': reIngestionRecord['data']}


def lambda_handler(event, context):
    streamARN = event['deliveryStreamArn']
    region = streamARN.split(':')[3]
    streamName = streamARN.split('/')[1]
    records = list(processRecords(event['records']))
    projectedSize = 0
    dataByRecordId = {rec['recordId']: createReingestionRecord(rec) for rec in event['records']}
    putRecordBatches = []
    recordsToReingest = []
    totalRecordsToBeReingested = 0

    for idx, rec in enumerate(records):
        projectedSize += len(rec['data']) + len(rec['recordId'])
        # 6000000 instead of 6291456 to leave ample headroom for the stuff we didn't account for
        if projectedSize > 6000000:
            totalRecordsToBeReingested += 1
            recordsToReingest.append(
                getReingestionRecord(dataByRecordId[rec['recordId']])
            )
            records[idx]['result'] = 'Dropped'
            del(records[idx]['data'])

        # split out the record batches into multiple groups, 500 records at max per group
        if len(recordsToReingest) == 500:
            putRecordBatches.append(recordsToReingest)
            recordsToReingest = []

    if len(recordsToReingest) > 0:
        # add the last batch
        putRecordBatches.append(recordsToReingest)

    # iterate and call putRecordBatch for each group
    recordsReingestedSoFar = 0
    if len(putRecordBatches) > 0:
        client = boto3.client('firehose', region_name=region)
        for recordBatch in putRecordBatches:
            putRecordsToFirehoseStream(streamName, recordBatch, client, attemptsMade=0, maxAttempts=20)
            recordsReingestedSoFar += len(recordBatch)
            print('Reingested %d/%d records out of %d' % (recordsReingestedSoFar, totalRecordsToBeReingested, len(event['records'])))
    else:
        print('No records to be reingested')

    return {"records": records}