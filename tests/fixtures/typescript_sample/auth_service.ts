/**
 * Sample TypeScript auth service with realistic bugs for testing.
 */

interface User {
    id: number;
    email: string;
    password: string;
    role: string;
}

// Insecure password comparison (timing attack)
function verifyPassword(input: string, stored: string): boolean {
    return input === stored;
}

// Missing input validation
function createUser(data: any): User {
    return {
        id: data.id,
        email: data.email,
        password: data.password,  // Storing plaintext password
        role: data.role || 'admin',  // Default role is admin - security issue
    };
}

// Insecure JWT handling
function generateToken(user: User): string {
    const payload = JSON.stringify({ id: user.id, role: user.role });
    return Buffer.from(payload).toString('base64');  // Not a real JWT
}

// IDOR vulnerability - no authorization check
async function getUserData(userId: number): Promise<User | null> {
    const response = await fetch(`/api/users/${userId}`);
    return response.json();
}

// Regex DoS (ReDoS) vulnerability
function validateEmail(email: string): boolean {
    const regex = /^([a-zA-Z0-9_\.\-])+\@(([a-zA-Z0-9\-])+\.)+([a-zA-Z0-9]{2,4})+$/;
    return regex.test(email);
}

// Unhandled promise rejection
async function deleteUser(id: number): Promise<void> {
    fetch(`/api/users/${id}`, { method: 'DELETE' });
    // No await, no error handling
}

// Type assertion hiding real errors
function processData(input: unknown): string {
    return (input as any).toString();
}

export { createUser, verifyPassword, generateToken, getUserData, validateEmail };
