import { request } from './client';
import type { User } from './types';

export function listUsers() {
  return request<User[]>({ method: 'GET', url: '/users' });
}

export function createUser(payload: {
  username: string;
  password: string;
  display_name: string;
  role: User['role'];
  home_location_id?: number | null;
}) {
  return request<User>({ method: 'POST', url: '/users', data: payload });
}

export function updateUser(
  id: number,
  payload: Partial<Pick<User, 'display_name' | 'role' | 'home_location_id' | 'is_active'>> & {
    password?: string;
  },
) {
  return request<User>({ method: 'PATCH', url: `/users/${id}`, data: payload });
}

export function deleteUser(id: number) {
  return request<null>({ method: 'DELETE', url: `/users/${id}` });
}
