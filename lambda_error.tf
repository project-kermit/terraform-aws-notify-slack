# When the lambda itself errors, that should:
# A) Feed back into the lambda, automatically
# B) Trigger a direct notification into a fallback SNS

resource "aws_cloudwatch_metric_alarm" "lambda_error" {
  count = "${var.create_fallback}"

  alarm_name = "${var.lambda_function_name} Failed"
  metric_name = "Errors"
  namespace = "AWS/Lambda"
  dimensions = {
    FunctionName = "${aws_lambda_function.notify_slack[0].function_name}"
  }
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold = "1"
  evaluation_periods = "1"
  period = "60"
  statistic = "Sum"
  treat_missing_data = "notBreaching"
  alarm_description = "Slack lambda which notifies about alerts has failed"
  alarm_actions = ["${var.fallback_sns}"]
}
