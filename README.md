# splunk-firehose-flowlogs-processor

This repo contains source code and supporting files for a serverless application that you can deploy with the SAM CLI. It includes the following files and folders.

- SplunkFirehoseFlowlogsProcessor - Code for the application's Lambda function.
- template.yaml - A template that defines the application's AWS resources.

The resources used by the application are defined in the `template.yaml` file in this project. You can update the template to add AWS resources through the same deployment process that updates your application code.

## Deployment

To manually package and deploy this project as an AWS SAM application

`sam package --template-file template.yaml --output-template-file package.yaml --s3-bucket <s3-bucket>`

`sam deploy --template-file <location of package.yaml> --stack-name <stack-name> --capabilities CAPABILITY_IAM`

## Resources

See the [AWS SAM developer guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/what-is-sam.html) for an introduction to SAM specification, the SAM CLI, and serverless application concepts.

Next, you can use AWS Serverless Application Repository to deploy ready to use Apps that go beyond hello world samples and learn how authors developed their applications: [AWS Serverless Application Repository main page](https://aws.amazon.com/serverless/serverlessrepo/)
