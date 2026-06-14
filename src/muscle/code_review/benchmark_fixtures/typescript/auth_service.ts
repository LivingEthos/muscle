interface User {
  id: number;
  email: string;
  password: string;
  role: string;
}

function createUser(data: any): User {
  return {
    id: data.id,
    email: data.email,
    password: data.password,
    role: data.role || 'admin',
  };
}

async function getUserData(userId: number): Promise<User | null> {
  const response = await fetch(`/api/users/${userId}`);
  return response.json();
}

async function deleteUser(id: number): Promise<void> {
  fetch(`/api/users/${id}`, { method: 'DELETE' });
}

export { createUser, getUserData, deleteUser };
