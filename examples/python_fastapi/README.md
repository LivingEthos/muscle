# FastAPI REST API with JWT Authentication

This example demonstrates building a complete REST API using FastAPI with JWT-based authentication, user registration/login, and CRUD operations for a todo list.

## Features

- **User Authentication**: Registration and login with JWT tokens
- **Password Security**: Bcrypt hashing with salt
- **RESTful API**: Full CRUD operations for todo items
- **Data Validation**: Pydantic models for request/response validation
- **Database**: SQLite with SQLAlchemy ORM
- **API Documentation**: Auto-generated OpenAPI/Swagger UI

## Tech Stack

- FastAPI - Modern Python web framework
- SQLAlchemy - SQL ORM
- Pydantic - Data validation
- python-jose - JWT token handling
- passlib/bcrypt - Password hashing
- uvicorn - ASGI server

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/register` | Register a new user |
| POST | `/auth/login` | Login and get JWT token |
| GET | `/todos` | List all todos (protected) |
| POST | `/todos` | Create a todo (protected) |
| GET | `/todos/{id}` | Get a specific todo (protected) |
| PUT | `/todos/{id}` | Update a todo (protected) |
| DELETE | `/todos/{id}` | Delete a todo (protected) |

## Usage

After SCLE generates the solution:

```bash
cd python_fastapi
pip install -r requirements.txt
uvicorn main:app --reload
```

Visit `http://localhost:8000/docs` for interactive API documentation.
