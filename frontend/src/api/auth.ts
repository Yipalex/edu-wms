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


// ========== 个人资料（头像 / 姓名 / 手机号，2026-11-04） ==========

/** 上传头像（multipart，字段名 file；前端已裁剪为正方形 PNG） */
export function uploadAvatar(file: File | Blob) {
  const fd = new FormData();
  fd.append('file', file, 'avatar.png');
  return request<{ avatar_url: string }>({
    method: 'POST',
    url: '/auth/avatar',
    data: fd,
  });
}

/** 修改姓名 / 手机号（username 即手机号，改号需验证原密码） */
export function updateProfile(payload: {
  display_name?: string;
  username?: string;
  old_password?: string;
}) {
  return request<User>({ method: 'POST', url: '/auth/profile', data: payload });
}

/** 头像图片地址（带版本号，改头像后自动破缓存） */
export function avatarUrl(userId: number, version?: number) {
  if (!userId) return '';
  return `/api/auth/avatars/${userId}` + (version ? `?v=${version}` : '');
}
