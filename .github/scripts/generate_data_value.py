#!/usr/bin/env python3

import os
import datetime
import random

# This script generates a data value for the GitHub project field

# Get input parameters from environment variables
issue_number = os.environ.get('ISSUE_NUMBER', 'unknown')
repository = os.environ.get('REPOSITORY', 'unknown')

# Generate a timestamp in a specific format
timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# Generate a random component for uniqueness
random_component = random.randint(1000, 9999)

# Generate the final data value
data_value = f"Data for issue #{issue_number} from {repository} generated at {timestamp} (ID: {random_component})"

# Output the value for GitHub Actions to capture
print(data_value)
