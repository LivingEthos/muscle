# Express.js REST API with TypeScript

This example demonstrates building a type-safe REST API using Express.js with TypeScript, input validation, and PostgreSQL database connection.

## Features

- **TypeScript**: Full type safety across the application
- **Input Validation**: Zod schema validation for all inputs
- **PostgreSQL**: Database connection using Prisma ORM
- **RESTful API**: Clean resource-based endpoints
- **Error Handling**: Centralized error middleware
- **Request Logging**: Morgan-based request logging

## Tech Stack

- Express.js - Node.js web framework
- TypeScript - Type safety
- Prisma - Database ORM
- Zod - Schema validation
- PostgreSQL - Relational database
- ts-node - TypeScript execution

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/users` | Register a new user |
| POST | `/api/users/login` | Authenticate user |
| GET | `/api/posts` | List all posts |
| POST | `/api/posts` | Create a post |
| GET | `/api/posts/{id}` | Get a specific post |
| PUT | `/api/posts/{id}` | Update a post |
| DELETE | `/api/posts/{id}` | Delete a post |

## Usage

After SCLE generates the solution:

```bash
cd javascript_ts
npm install
npx prisma generate
npx prisma db push
npm run dev
```

The API will be available at `http://localhost:3000/api`.
