import { request } from './client';
import type { LoginResult, User } from './types';

export function login(username: string, password: string) {
  return request<LoginResult>({
    method: 'POST',
    url: '/auth/login',
    data: { username, password },
  });
}

export function getMe() {
  return request<User>({ method: 'GET', url: '/auth/me' });
}

export function logout() {
  return request<null>({ method: 'POST', url: '/auth/logout' });
}

export function changePassword(old_password: string, new_password: string) {
  return request<null>({
    method: 'POST',
    url: '/auth/change-password',
    data: { old_password, new_password },
  });
}
