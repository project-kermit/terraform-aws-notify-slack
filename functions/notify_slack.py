from __future__ import print_function
import os, boto3, json, base64
import urllib.request, urllib.parse
import logging
from email.utils import parsedate_tz, mktime_tz
from datetime import datetime, timezone, timedelta


# Decrypt encrypted URL with KMS
def decrypt(encrypted_url):
    region = os.environ['AWS_REGION']
    try:
        kms = boto3.client('kms', region_name=region)
        plaintext = kms.decrypt(CiphertextBlob=base64.b64decode(encrypted_url))['Plaintext']
        return plaintext.decode()
    except Exception:
        logging.exception("Failed to decrypt URL with KMS")


def cloudwatch_notification(message, region):
    states = {'OK': 'good', 'INSUFFICIENT_DATA': 'warning', 'ALARM': 'danger'}

    return {
            "color": states[message['NewStateValue']],
            "fallback": "Alarm {} triggered".format(message['AlarmName']),
            "fields": [
                { "title": "Alarm Name", "value": message['AlarmName'], "short": True },
                { "title": "Alarm Description", "value": message['AlarmDescription'], "short": False},
                { "title": "Alarm reason", "value": message['NewStateReason'], "short": False},
                { "title": "Old State", "value": message['OldStateValue'], "short": True },
                { "title": "Current State", "value": message['NewStateValue'], "short": True },
                {
                    "title": "Link to Alarm",
                    "value": "https://console.aws.amazon.com/cloudwatch/home?region=" + region + "#alarm:alarmFilter=ANY;name=" + urllib.parse.quote_plus(message['AlarmName']),
                    "short": False
                }
            ]
        }


def rds_notification(message):
    return {
            "color": 'warning',
            "fallback": "{} incurred a {}".format(message['Source ID'], message['Event Message']),
            "fields": [
                { "title": "Database", "value": message['Source ID'], "short": True },
                { "title": "Message", "value": message['Event Message'], "short": True},
                { "title": "Link to DB", "value": message['Identifier Link'], "short": False },
                { "title": "Message Meaning", "value": message['Event ID'], "short": False },
            ]
        }

def glue_notification(message, region, log_group):
    return {
            "color": message['Status'],
            "fallback": "Glue job {} has a status of ".format(message['Job'], message['Status']),
            "fields": [
                { "title": "Job", "value": message['Job'], "short": True },
                { "title": "Rows Affected", "value": message['Rows'], "short": True},
                { "title": "Finshed Date", "value": message['Date'], "short": True},
                { "title": "Environment", "value": log_group, "short": True}
            ]
        }

def codedeploy_notification(message, region, log_group):
    statuses = {'CREATED': '',
                'SUCCEEDED': 'good',
                'STOPPED': 'warning',
                'FAILED': 'danger',
                }

    fields = [
            {'title': 'Deployment Group', 'value': message['deploymentGroupName'], 'short': True},
            {'title': 'Action', 'value': message['status'].title(), 'short': True},
            {'title': 'Create Time', 'value': '<!date^{}^{{date_short}} {{time}}|{}>'.format(mktime_tz(parsedate_tz(message['createTime'])), message['createTime']), 'short': True}
            ]

    if message.get('completeTime'):
        fields.append({'title': 'Complete Time', 'value': '<!date^{}^{{date_short}} {{time}}|{}>'.format(mktime_tz(parsedate_tz(message['completeTime'])), message['completeTime']), 'short': True})

    if 'deploymentOverview' in message:
        do = json.loads(message['deploymentOverview'])
        fields.append({'title': 'Deployment Overview', 'value': ' — '.join(  k + ": " + str(v) for (k, v) in do.items()), 'short': False})
        
    now = datetime.now(timezone.utc)
    ten_mins_ago = now - timedelta(minutes = 10)
    ten_mins_ahead = now + timedelta(minutes = 10)
    log_filter = "{$.PRIORITY=\"3\"}"
    
    if message.get('completeTime'):
        fields.append({"title": "Link to Logs",
                       "value": "https://" + region + ".console.aws.amazon.com/cloudwatch/home?region=" + region + "#logEventViewer:group="+ log_group + ";filter=" + urllib.parse.quote_plus(log_filter) + ";start=" + ten_mins_ago.astimezone().isoformat() + ";end=" + ten_mins_ahead.astimezone().isoformat(),
                       "short": False})

    return {
            'color': statuses.get(message['status'], ''),
            'fallback': 'Deployment {} for {} at {} until {}'.format(
                message['status'].title(),
                message['deploymentGroupName'],
                message['createTime'],
                message['completeTime'],
                ),
            'fields': fields,
        }


def default_notification(message):
    return {
            "fallback": "A new message",
            "fields": [{"title": "Message", "value": json.dumps(message), "short": False}]
        }


# Send a message to a slack channel
def notify_slack(message, region):
    slack_url = os.environ['SLACK_WEBHOOK_URL']
    if not slack_url.startswith("http"):
        slack_url = decrypt(slack_url)

    slack_channel = os.environ['SLACK_CHANNEL']
    slack_username = os.environ['SLACK_USERNAME']
    slack_emoji = os.environ['SLACK_EMOJI']

    log_group = os.environ['LOG_GROUP']

    payload = {
        "channel": slack_channel,
        "username": slack_username,
        "icon_emoji": slack_emoji,
        "attachments": []
    }
    if "AlarmName" in message:
        notification = cloudwatch_notification(message, region)
        payload['text'] = "AWS CloudWatch notification - " + message["AlarmName"]
        payload['attachments'].append(notification)
    elif "Event Source" in message and message["Event Source"] == "db-instance":
        notification = rds_notification(message)
        payload['text'] = "AWS RDS notification - " + message["Event Message"]
        payload['attachments'].append(notification)
    elif 'deploymentId' in message:
        notification = codedeploy_notification(message, region, log_group)
        payload['text'] = "AWS CodeDeploy notification"
        payload['attachments'].append(notification)
    if "Job" in message:
        notification = glue_notification(message, region, log_group)
        payload['text'] = "AWS Glue notification"
        payload['attachments'].append(notification)
    else:
        payload['text'] = "AWS notification"
        payload['attachments'].append(default_notification(message))

    data = urllib.parse.urlencode({"payload": json.dumps(payload)}).encode("utf-8")
    req = urllib.request.Request(slack_url)
    urllib.request.urlopen(req, data)


def lambda_handler(event, context):
    message = json.loads(event['Records'][0]['Sns']['Message'])
    region = event['Records'][0]['Sns']['TopicArn'].split(":")[3]
    notify_slack(message, region)

    return message

#notify_slack({"AlarmName":"Example","AlarmDescription":"Example alarm description.","AWSAccountId":"000000000000","NewStateValue":"ALARM","NewStateReason":"Threshold Crossed","StateChangeTime":"2017-01-12T16:30:42.236+0000","Region":"EU - Ireland","OldStateValue":"OK"}, "eu-west-1")
