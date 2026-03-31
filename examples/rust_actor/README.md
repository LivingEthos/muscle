# Rust Actor Model Project

This example demonstrates building a Rust application using the actor model with message passing between components.

## Features

- **Actor Model**: True actor-based concurrency
- **Message Passing**: Type-safe message passing between actors
- **Supervision**: Actor supervision and fault tolerance
- **Async/Await**: Modern async Rust with Tokio
- **Type Safety**: Full Rust type safety for messages

## Tech Stack

- Rust - Programming language
- Actix - Actor framework
- Tokio - Async runtime
- serde - Serialization

## Architecture

The application simulates a distributed task processor with:
- **TaskManager Actor**: Coordinates task distribution
- **Worker Actor**: Processes individual tasks
- **ResultCollector Actor**: Aggregates results

## Actors and Messages

### TaskManager
- `RegisterWorker` - Register a new worker
- `SubmitTask` - Submit a task for processing
- `GetStatus` - Get overall system status

### Worker
- `ProcessTask` - Process a specific task
- `TaskComplete` - Report task completion
- `TaskFailed` - Report task failure

### ResultCollector
- `CollectResult` - Collect a processed result
- `GetResults` - Get all collected results

## Usage

After SCLE generates the solution:

```bash
cd rust_actor
cargo run
```

The application will start and demonstrate actor message passing with concurrent task processing.
