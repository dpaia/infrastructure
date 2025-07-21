#!/usr/bin/env kotlinc -script

import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import kotlin.random.Random

// This script generates a data value for the GitHub project field

// Generate a timestamp in a specific format
val timestamp = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))

// Get input parameters from environment variables
val issueNumber = System.getenv("ISSUE_NUMBER") ?: "unknown"
val repository = System.getenv("REPOSITORY") ?: "unknown"

// Generate a random component for uniqueness
val randomComponent = Random.nextInt(1000, 9999)

// Generate the final data value
val dataValue = "Data for issue #$issueNumber from $repository generated at $timestamp (ID: $randomComponent)"

// Output the value for GitHub Actions to capture
println(dataValue)
