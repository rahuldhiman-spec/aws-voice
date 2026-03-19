# Deployment Guide

This guide is written in plain language on purpose.

The goal is simple:

1. Build the Lambda code.
2. Package the runtime files.
3. Deploy the package to AWS Lambda.
4. Configure the Lambda so it can call SUVA.
5. Test one real request end to end.

## Before You Start

Think of this repo as a translator.

- Upstream sends a normalized request to Lambda.
- Lambda calls SUVA.
- Lambda returns a safe adapter response.

Important:

- This handler does **not** accept a raw Lex event today.
- It expects a normalized `SuvaRequest` shape.
- If you wire raw Lex directly to this function, the request will fail validation.

The deployed handler entry point is:

```text
dist/lambda/adapter/handler.handler
```

## What You Need

- Node.js 20+
- npm 10+
- AWS account access
- Permission to create or update Lambda functions
- A reachable SUVA base URL
- AWS CLI configured locally if you want to deploy from the terminal

## Step 1: Install Dependencies

This gives you the tools needed to build and test the project.

```bash
npm install
```

## Step 2: Verify the Code Before You Ship It

This step is your safety check.
If this fails locally, deployment is usually just a slower way to discover the same problem.

```bash
npm run lint
npm run typecheck
npm run test
npm run build
```

If you want one command:

```bash
npm run verify
```

Note:

- `npm run format` currently fails because `README.md` has a pre-existing formatting issue.
- That does not block the Lambda build itself.

## Step 3: Build the Lambda Output

TypeScript source files are not what Lambda runs.
Lambda runs the compiled JavaScript in `dist/`.

```bash
npm run build
```

After this, the important runtime files will be under:

```text
dist/lambda/adapter/
dist/contracts/
```

## Step 4: Create a Deployment Package

Lambda needs two things in the zip:

- the compiled `dist/` folder
- production dependencies from `node_modules/`

The clean way to do that is to build the zip in a temporary folder.

```bash
rm -rf .deploy
mkdir -p .deploy/lambda

cp package.json package-lock.json .deploy/lambda/
npm ci --omit=dev --prefix .deploy/lambda

npm run build
cp -R dist .deploy/lambda/

(cd .deploy/lambda && zip -r ../qualys-voice-bridge.zip .)
```

At the end of this step, your deployment artifact is:

```text
.deploy/qualys-voice-bridge.zip
```

## Step 5: Create the Lambda Execution Role

The Lambda needs permission to write logs to CloudWatch.

At minimum, attach the standard AWS managed policy:

```text
AWSLambdaBasicExecutionRole
```

If SUVA is reachable over the public internet, that is usually enough.

If SUVA is inside a private network:

- place the Lambda in the right VPC
- attach the needed security groups
- make sure outbound routing exists, usually through NAT or private connectivity

## Step 6: Create the Lambda Function

You can do this in the AWS Console or with AWS CLI.

Recommended runtime settings for a first deployment:

- Runtime: `nodejs20.x`
- Architecture: `x86_64` or `arm64`
- Handler: `dist/lambda/adapter/handler.handler`
- Timeout: `10` seconds
- Memory: `256` MB

Example AWS CLI command:

```bash
aws lambda create-function \
  --function-name qualys-voice-bridge \
  --runtime nodejs20.x \
  --role arn:aws:iam::<account-id>:role/<lambda-role-name> \
  --handler dist/lambda/adapter/handler.handler \
  --zip-file fileb://.deploy/qualys-voice-bridge.zip
```

If the function already exists, update the code instead:

```bash
aws lambda update-function-code \
  --function-name qualys-voice-bridge \
  --zip-file fileb://.deploy/qualys-voice-bridge.zip
```

## Step 7: Set Environment Variables

The main setting this Lambda needs is the SUVA base URL.

Set at least:

- `SUVA_BASE_URL`

Optional:

- `AWS_REGION`
- `LOG_LEVEL`

Example:

```bash
aws lambda update-function-configuration \
  --function-name qualys-voice-bridge \
  --environment "Variables={SUVA_BASE_URL=https://suva.example.com}"
```

## Step 8: Send a Smoke-Test Event

This is the fastest way to prove the deployment works before wiring real traffic to it.

Create a test payload like this:

```json
{
  "sessionId": "session-123",
  "callerId": "+15551234567",
  "language": "en-US",
  "utterance": "Check my open findings",
  "metadata": {
    "awsContactId": "contact-123",
    "source": "amazon-connect-lex"
  }
}
```

Invoke the function:

```bash
aws lambda invoke \
  --function-name qualys-voice-bridge \
  --payload fileb://event.json \
  response.json
```

What good looks like:

- Lambda returns JSON
- `awsContactId` is present in the response
- `voiceText` is short and cleaned for speech
- CloudWatch logs contain structured JSON entries
- The log entry includes `sessionId`, `awsContactId`, status, and SUVA response time

## Step 9: Wire the Upstream Caller

Only do this after the smoke test passes.

Remember the key rule:

- upstream must send the normalized `SuvaRequest` contract
- upstream must include `metadata.awsContactId`

That `awsContactId` is the correlation key used to map:

```text
AWS call <-> Lambda logs <-> SUVA analytics
```

## Step 10: Know the Main Failure Modes

If something breaks, these are the first places to look.

### Validation Failure

What it means:

- the incoming event is not shaped like `SuvaRequest`
- or `utterance` / `awsContactId` is blank

What to check:

- upstream payload mapping
- missing `metadata.awsContactId`
- raw Lex event accidentally sent to this Lambda

### `ESCALATE` Response

What it means:

- SUVA timed out
- SUVA returned an invalid payload
- confidence was below the adapter threshold
- SUVA was unreachable or unavailable

What to check:

- `reason` field in the Lambda response
- structured CloudWatch log entry for the same `awsContactId`

### No Connection to SUVA

What it means:

- bad `SUVA_BASE_URL`
- DNS or network path problem
- VPC routing issue
- security group egress issue

What to check:

- Lambda environment variables
- VPC config
- outbound network path from Lambda

## Step 11: Safe Update Flow

When you deploy a change later, use the same rhythm every time:

1. Run local verification.
2. Build a fresh zip.
3. Update Lambda code.
4. Run one smoke test.
5. Confirm CloudWatch logs for the new request.

This keeps deployment boring, which is the real goal.
