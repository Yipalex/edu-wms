import { request } from './client';
import type { Category, Location } from './types';

export function listCategories() {
  return request<Category[]>({ method: 'GET', url: '/categories' });
}

export function createCategory(payload: { digit: string; name: string; sort_order?: number }) {
  return request<Category>({ method: 'POST', url: '/categories', data: payload });
}

/** digit 改动需 confirm_digit=true（后端会警告影响新码构成） */
export function updateCategory(
  id: number,
  payload: Partial<Pick<Category, 'name' | 'digit' | 'sort_order' | 'is_active'>>,
  confirmDigit = false,
) {
  return request<Category>({
    method: 'PATCH',
    url: `/categories/${id}`,
    params: confirmDigit ? { confirm_digit: 'true' } : undefined,
    data: payload,
  });
}

export function listLocations() {
  return request<Location[]>({ method: 'GET', url: '/locations' });
}

export function updateLocation(id: number, payload: Partial<Location>) {
  return request<Location>({ method: 'PATCH', url: `/locations/${id}`, data: payload });
}
