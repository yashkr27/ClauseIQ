import boto3
import json

client = boto3.client('bedrock-runtime', region_name='ap-southeast-2')

# Try system-defined Claude 3.5 Haiku apac profile ID
try:
    print("Testing system-defined profile ID in ap-southeast-2: apac.anthropic.claude-3-5-haiku-20241022-v1:0...")
    response = client.converse(
        modelId='apac.anthropic.claude-3-5-haiku-20241022-v1:0',
        messages=[{"role": "user", "content": [{"text": "Reply with OK"}]}]
    )
    print("apac Claude 3.5 Haiku SUCCESS:", response["output"]["message"]["content"][0]["text"])
except Exception as e:
    print("apac Claude 3.5 Haiku FAILED:", str(e)[:200])

# Try system-defined Claude 4.5 Haiku apac profile ID
try:
    print("\nTesting system-defined profile ID in ap-southeast-2: apac.anthropic.claude-haiku-4-5-20251001-v1:0...")
    response = client.converse(
        modelId='apac.anthropic.claude-haiku-4-5-20251001-v1:0',
        messages=[{"role": "user", "content": [{"text": "Reply with OK"}]}]
    )
    print("apac Claude 4.5 Haiku SUCCESS:", response["output"]["message"]["content"][0]["text"])
except Exception as e:
    print("apac Claude 4.5 Haiku FAILED:", str(e)[:200])
