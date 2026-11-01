/**
 * Mock 处理器：拦截 request(config)，按 方法+路径 匹配返回假数据。
 * 数据结构严格按契约（成功 = data 本体；分页接口返回 { list, meta }）。
 * 开启方式：npm run dev:mock，或任意 URL 加 ?mock=1（记忆到 localStorage，?mock=0 关闭）。
 */
import type { AxiosRequestConfig } from 'axios';
import {
  MOCK_BARCODE_HISTORY,
  MOCK_CATEGORIES,
  MOCK_INVENTORY,
  MOCK_ITEMS,
  MOCK_LOCATIONS,
  MOCK_MOVEMENTS,
  MOCK_RULES,
  MOCK_USERS,
  MERGED_ITEM,
  categoryName,
  findItemByBarcode,
  locationName,
  mockPhoto,
} from './data';
import type {
  BarcodePreviewResult,
  DashboardData,
  Item,
  ItemDetail,
  ScanResolveResult,
  User,
} from '@/api/types';

let nextItemId = 1000;
let nextPhotoId = 1;
let nextUserId = 100;
let nextHistoryId = 100;

function delay(ms = 150): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function paginate<T>(all: T[], params: Record<string, unknown>) {
  const page = Number(params.page ?? 1);
  const pageSize = Number(params.page_size ?? 20);
  const start = (page - 1) * pageSize;
  return {
    list: all.slice(start, start + pageSize),
    meta: { page, page_size: pageSize, total: all.length },
  };
}

function toItemDetail(item: Item): ItemDetail {
  const inv = MOCK_INVENTORY.filter((r) => r.item_id === item.id).map((r) => ({
    item_id: item.id,
    location_id: r.location_id,
    location_name: locationName(r.location_id),
    qty_on_hand: r.qty_on_hand,
    qty_reserved: r.qty_reserved,
    safety_stock: r.safety_stock,
  }));
  return {
    ...item,
    photos: item.primary_photo_url
      ? [
          {
            id: item.id,
            item_id: item.id,
            file_path: '',
            sort_order: 0,
            is_primary: true,
            source: 'upload',
            url: item.primary_photo_url,
          },
        ]
      : [],
    inventory: inv,
    recent_movements: MOCK_MOVEMENTS.filter((m) => m.item_id === item.id).slice(0, 5),
    aliases:
      item.id === 30
        ? [{ id: 1, item_id: 30, alias: '铅 笔', source: 'migration' }]
        : item.id === 17
          ? [{ id: 2, item_id: 17, alias: '红星墨汁', source: 'migration' }]
          : [],
    barcode_history: MOCK_BARCODE_HISTORY.filter((h) => h.item_id === item.id),
  };
}

function movementsForItem(itemId: number) {
  return MOCK_MOVEMENTS.filter((m) => m.item_id === itemId).slice(0, 5);
}

/** Mock 版标签 PDF：生成一个简单可打印 HTML blob（真实环境由后端 Pillow 出 PDF） */
function mockLabelPdf(itemIds: number[], copies: number, layout: string): string {
  const items = MOCK_ITEMS.filter((i) => itemIds.includes(i.id));
  const cols = layout === '4col' ? 4 : 3;
  let cells = '';
  items.forEach((it) => {
    for (let c = 0; c < copies; c++) {
      cells += `<div style="border:1px solid #ccc;padding:8px;margin:4px;width:${Math.floor(95 / cols)}%;display:inline-block;text-align:center;font-family:sans-serif">
        <div style="font-family:monospace;letter-spacing:2px;font-size:20px">||||| |||| |||||</div>
        <div style="font-weight:bold">${it.barcode ?? '待编码'}</div>
        <div>${it.name}</div>
        <div style="font-size:11px;color:#666">${categoryName(it.category_id)}${it.spec ? ' · ' + it.spec : ''}</div>
      </div>`;
    }
  });
  const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>标签预览（Mock）</title></head><body>${cells}<p style="color:#999">Mock 模式生成的预览页，非真实 PDF。接入后端后由 GET /labels/pdf 输出 300dpi 打印版。</p></body></html>`;
  const blob = new Blob([html], { type: 'text/html' });
  return URL.createObjectURL(blob);
}

export async function handleMock<T>(config: AxiosRequestConfig): Promise<T> {
  await delay();
  const method = (config.method ?? 'get').toUpperCase();
  const url = config.url ?? '';
  const params = (config.params ?? {}) as Record<string, unknown>;
  const body = (typeof config.data === 'string' ? safeJson(config.data) : (config.data ?? {})) as Record<string, unknown>;

  // ===== 认证 =====
  if (url === '/auth/login' && method === 'POST') {
    const { username, password } = body as { username: string; password: string };
    const user = MOCK_USERS.find((u) => u.username === username);
    if (!user || password !== '123456') {
      throw new Error('用户名或密码错误（Mock 账号：admin / 123456）');
    }
    if (!user.is_active) throw new Error('该账号已停用，请联系管理员');
    return {
      access_token: `mock-access-${user.id}`,
      refresh_token: `mock-refresh-${user.id}`,
      user,
    } as T;
  }
  if (url === '/auth/me' && method === 'GET') return MOCK_USERS[0] as T;
  if (url === '/auth/logout' && method === 'POST') return null as T;
  if (url === '/auth/change-password' && method === 'POST') return null as T;
  if (url === '/auth/refresh' && method === 'POST') {
    return { access_token: `mock-access-refreshed-${Date.now()}` } as T;
  }

  // ===== 用户管理 =====
  if (url === '/users' && method === 'GET') return MOCK_USERS as T;
  if (url === '/users' && method === 'POST') {
    const u = {
      id: nextUserId++,
      username: String(body.username),
      display_name: String(body.display_name),
      role: body.role as User['role'],
      home_location_id: (body.home_location_id as number) ?? null,
      is_active: true,
      last_login_at: null,
    };
    MOCK_USERS.push(u);
    return u as T;
  }
  const userMatch = url.match(/^\/users\/(\d+)$/);
  if (userMatch) {
    const u = MOCK_USERS.find((x) => x.id === Number(userMatch[1]));
    if (!u) throw new Error('用户不存在');
    if (method === 'PATCH') Object.assign(u, body);
    if (method === 'DELETE') u.is_active = false;
    return u as T;
  }

  // ===== 库位 / 类目 / 编码规则 =====
  if (url === '/locations' && method === 'GET') return MOCK_LOCATIONS as T;
  if (url === '/categories' && method === 'GET') return MOCK_CATEGORIES as T;
  const catMatch = url.match(/^\/categories\/(\d+)$/);
  if (catMatch && method === 'PATCH') {
    const c = MOCK_CATEGORIES.find((x) => x.id === Number(catMatch[1]));
    if (!c) throw new Error('类目不存在');
    if (body.digit && body.digit !== c.digit && params.confirm_digit !== 'true') {
      throw new Error('修改数字位会影响后续新条码构成，需二次确认');
    }
    Object.assign(c, body);
    return c as T;
  }
  if (url === '/barcode-rules' && method === 'GET') return MOCK_RULES as T;
  if (url === '/barcode-rules' && method === 'PUT') {
    Object.assign(MOCK_RULES, body);
    return MOCK_RULES as T;
  }

  // ===== 条码 =====
  if (url === '/barcode/preview' && method === 'POST') {
    const catId = Number(body.category_id);
    const cat = MOCK_CATEGORIES.find((c) => c.id === catId);
    if (!cat) throw new Error('类目不存在');
    const used = MOCK_ITEMS.filter(
      (i) => i.barcode?.length === 8 && i.barcode[3] === cat.digit && i.barcode.startsWith('210'),
    ).map((i) => Number(i.barcode!.slice(4)));
    const nextSeq = (used.length ? Math.max(...used) : 0) + 1;
    const barcode = `${MOCK_RULES.prefix}${MOCK_RULES.region_code}${cat.digit}${String(nextSeq).padStart(4, '0')}`;
    return { barcode, category_id: catId, category_digit: cat.digit, next_seq: nextSeq } as BarcodePreviewResult as T;
  }
  if (url === '/barcode/allocate' && method === 'POST') {
    const itemIds = (body.item_ids as number[]) ?? (body.item_id ? [Number(body.item_id)] : []);
    const catId = body.category_id ? Number(body.category_id) : null;
    const allocated: { item_id: number; barcode: string }[] = [];
    itemIds.forEach((id) => {
      const item = MOCK_ITEMS.find((i) => i.id === id);
      if (!item) return;
      const cat = MOCK_CATEGORIES.find((c) => c.id === (catId ?? item.category_id))!;
      const used = MOCK_ITEMS.filter(
        (i) => i.barcode?.length === 8 && i.barcode[3] === cat.digit && i.barcode.startsWith('210'),
      ).map((i) => Number(i.barcode!.slice(4)));
      const seq = (used.length ? Math.max(...used) : 0) + 1;
      item.barcode = `${MOCK_RULES.prefix}${MOCK_RULES.region_code}${cat.digit}${String(seq).padStart(4, '0')}`;
      MOCK_BARCODE_HISTORY.unshift({
        id: nextHistoryId++, item_id: item.id, item_name: item.name,
        old_barcode: null, new_barcode: item.barcode, change_type: 'assign',
        reason: '待编码物品批量分配', operator_id: 1, operator_name: '系统管理员',
        created_at: new Date().toISOString(),
      });
      allocated.push({ item_id: item.id, barcode: item.barcode });
    });
    return { allocated } as T;
  }
  if (url === '/barcode/history' && method === 'GET') {
    let rows = [...MOCK_BARCODE_HISTORY];
    if (params.change_type) rows = rows.filter((r) => r.change_type === params.change_type);
    if (params.start_date) rows = rows.filter((r) => r.created_at >= String(params.start_date));
    if (params.end_date) rows = rows.filter((r) => r.created_at <= String(params.end_date) + 'T23:59:59');
    return paginate(rows, params) as T;
  }
  const itemHistMatch = url.match(/^\/items\/(\d+)\/barcode-history$/);
  if (itemHistMatch && method === 'GET') {
    return MOCK_BARCODE_HISTORY.filter((h) => h.item_id === Number(itemHistMatch[1])) as T;
  }

  // ===== 扫码解析（四分支） =====
  if (url === '/scan/resolve' && method === 'GET') {
    const code = String(params.code ?? '');
    // 分支 2：已合并（21010002 → 合并至 21010001「偏旁部首上」）
    if (code === '21010002') {
      return {
        resolved: false,
        code,
        code_type: 'internal',
        item: null,
        inventory: null,
        total_qty: null,
        hint: `该物品已合并至「${MOCK_ITEMS[0].name}」`,
        redirect_barcode: '21010001',
      } as ScanResolveResult as T;
    }
    // 分支 3：旧码停用（21040024 → 现用码 21040025）
    const retired = MOCK_BARCODE_HISTORY.find(
      (h) => h.old_barcode === code && (h.change_type === 'reassign' || h.change_type === 'merge_retire'),
    );
    if (retired && retired.new_barcode) {
      return {
        resolved: false,
        code,
        code_type: 'internal',
        item: null,
        inventory: null,
        total_qty: null,
        hint: `该条码已停用（重新分配），现用码 ${retired.new_barcode}`,
        new_barcode: retired.new_barcode,
      } as ScanResolveResult as T;
    }
    // 分支 1：命中
    const item = findItemByBarcode(code);
    if (item && item.status === 'active') {
      const inv = MOCK_INVENTORY.filter((r) => r.item_id === item.id).map((r) => ({
        location_id: r.location_id,
        location_name: locationName(r.location_id),
        qty_on_hand: r.qty_on_hand,
        qty_reserved: r.qty_reserved,
        safety_stock: r.safety_stock,
      }));
      return {
        resolved: true,
        code,
        code_type: item.barcode_origin === 'external' ? 'external' : 'internal',
        item: {
          id: item.id,
          barcode: item.barcode,
          name: item.name,
          category: categoryName(item.category_id),
          spec: item.spec,
          suggest_price: item.suggest_price,
          need_label: item.need_label,
          photo_url: item.primary_photo_url,
        },
        inventory: inv,
        total_qty: inv.reduce((s, r) => s + r.qty_on_hand, 0),
        hint: null,
        recent_movements: movementsForItem(item.id),
      } as ScanResolveResult as T;
    }
    // 分支 4：完全未登记
    return {
      resolved: false,
      code,
      code_type: 'unknown',
      item: null,
      inventory: null,
      total_qty: null,
      hint: '未登记的条码',
    } as ScanResolveResult as T;
  }

  // ===== 物品 =====
  if (url === '/items' && method === 'GET') {
    let rows = [...MOCK_ITEMS];
    const q = params.q ? String(params.q).toLowerCase() : '';
    if (q) {
      rows = rows.filter(
        (i) => i.name.toLowerCase().includes(q) || (i.barcode ?? '').includes(q),
      );
    }
    if (params.category_id) rows = rows.filter((i) => i.category_id === Number(params.category_id));
    if (params.status) rows = rows.filter((i) => i.status === params.status);
    if (params.need_label !== undefined && params.need_label !== '') {
      rows = rows.filter((i) => i.need_label === (params.need_label === true || params.need_label === 'true'));
    }
    if (params.print_mode) rows = rows.filter((i) => i.print_mode === params.print_mode);
    if (params.has_photo !== undefined && params.has_photo !== '') {
      const want = params.has_photo === true || params.has_photo === 'true';
      rows = rows.filter((i) => !!i.primary_photo_url === want);
    }
    if (params.pending_code === true || params.pending_code === 'true') {
      rows = rows.filter((i) => !i.barcode);
    }
    rows.forEach((i) => {
      i.total_qty = MOCK_INVENTORY.filter((r) => r.item_id === i.id).reduce((s, r) => s + r.qty_on_hand, 0);
    });
    return paginate(rows, params) as T;
  }
  if (url === '/items' && method === 'POST') {
    const item: Item = {
      id: nextItemId++,
      barcode: (body.barcode as string) || null,
      name: String(body.name ?? ''),
      category_id: Number(body.category_id),
      category_name: categoryName(Number(body.category_id)),
      spec: String(body.spec ?? ''),
      suggest_price: (body.suggest_price as number) ?? null,
      unit: String(body.unit ?? '件'),
      need_label: body.need_label !== false,
      print_mode: (body.print_mode as Item['print_mode']) ?? 'label',
      status: 'active',
      merged_into_id: null,
      barcode_origin:
        body.barcode && String(body.barcode).length !== 8 ? 'external' : 'internal',
      remark: String(body.remark ?? ''),
      primary_photo_url: mockPhoto(String(body.name ?? '新物品'), nextItemId % 360),
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    if (item.barcode && findItemByBarcode(item.barcode)) throw new Error('条码已存在，请更换');
    MOCK_ITEMS.unshift(item);
    return item as T;
  }
  const itemMatch = url.match(/^\/items\/(\d+)$/);
  if (itemMatch) {
    const id = Number(itemMatch[1]);
    const item = MOCK_ITEMS.find((i) => i.id === id) ?? (id === MERGED_ITEM.id ? MERGED_ITEM : undefined);
    if (!item) throw new Error('物品不存在');
    if (method === 'GET') return toItemDetail(item) as T;
    if (method === 'PATCH') {
      Object.assign(item, body);
      return item as T;
    }
    if (method === 'DELETE') {
      (item as Item).status = 'retired';
      return null as T;
    }
  }
  const photoMatch = url.match(/^\/items\/(\d+)\/photos$/);
  if (photoMatch && method === 'POST') {
    return { id: nextPhotoId++, url: mockPhoto('已上传照片', nextPhotoId * 53 % 360) } as T;
  }
  const photoOpMatch = url.match(/^\/items\/(\d+)\/photos\/(\d+)$/);
  if (photoOpMatch) {
    if (method === 'PATCH') return null as T; // 设主图
    if (method === 'DELETE') return null as T; // 删照片
  }

  // ===== 库存 / 流水 =====
  if (url === '/inventory' && method === 'GET') {
    let rows = MOCK_INVENTORY.map((r) => {
      const item = MOCK_ITEMS.find((i) => i.id === r.item_id);
      return {
        item_id: r.item_id,
        item_name: item?.name ?? '',
        barcode: item?.barcode ?? null,
        location_id: r.location_id,
        location_name: locationName(r.location_id),
        qty_on_hand: r.qty_on_hand,
        qty_reserved: r.qty_reserved,
        safety_stock: r.safety_stock,
      };
    });
    if (params.location_id) rows = rows.filter((r) => r.location_id === Number(params.location_id));
    if (params.below_safety === true || params.below_safety === 'true') {
      rows = rows.filter((r) => r.safety_stock > 0 && r.qty_on_hand < r.safety_stock);
    }
    if (params.q) {
      const q = String(params.q);
      rows = rows.filter((r) => r.item_name.includes(q) || (r.barcode ?? '').includes(q));
    }
    return paginate(rows, params) as T;
  }
  if (url === '/movements' && method === 'GET') {
    return paginate(MOCK_MOVEMENTS, params) as T;
  }

  // ===== 仪表盘 =====
  if (url === '/reports/dashboard' && method === 'GET') {
    const locationValues = MOCK_LOCATIONS.map((loc) => {
      const rows = MOCK_INVENTORY.filter((r) => r.location_id === loc.id);
      const value = rows.reduce((s, r) => {
        const item = MOCK_ITEMS.find((i) => i.id === r.item_id);
        return s + (item?.suggest_price ?? 0) * r.qty_on_hand;
      }, 0);
      return {
        location_id: loc.id,
        location_name: loc.name,
        location_code: loc.code,
        sku_count: new Set(rows.map((r) => r.item_id)).size,
        total_qty: rows.reduce((s, r) => s + r.qty_on_hand, 0),
        total_value: Math.round(value * 100) / 100,
      };
    });
    const lowStock = MOCK_INVENTORY.filter((r) => r.safety_stock > 0 && r.qty_on_hand < r.safety_stock)
      .slice(0, 8)
      .map((r) => {
        const item = MOCK_ITEMS.find((i) => i.id === r.item_id)!;
        return {
          item_id: r.item_id,
          item_name: item.name,
          barcode: item.barcode,
          location_id: r.location_id,
          location_name: locationName(r.location_id),
          qty_on_hand: r.qty_on_hand,
          safety_stock: r.safety_stock,
        };
      });
    return {
      item_count: MOCK_ITEMS.filter((i) => i.status === 'active').length,
      total_qty: MOCK_INVENTORY.reduce((s, r) => s + r.qty_on_hand, 0),
      total_reserved: MOCK_INVENTORY.reduce((s, r) => s + r.qty_reserved, 0),
      stocktake_count: 12,
      pending_stocktakes: 1,
      today_in_count: 3,
      today_out_count: 5,
      by_location: locationValues,
      low_stock: lowStock,
      recent_movements: MOCK_MOVEMENTS.slice(0, 8),
    } as DashboardData as T;
  }

  // ===== 标签 PDF（mock 返回可预览的 blob URL） =====
  if (url === '/labels/pdf' && method === 'GET') {
    const ids = String(params.item_ids ?? '').split(',').map(Number).filter(Boolean);
    return mockLabelPdf(ids, Number(params.copies ?? 1), String(params.layout ?? '3col')) as T;
  }

  throw new Error(`Mock 未实现的接口：${method} ${url}`);
}

function safeJson(s: string): unknown {
  try {
    return JSON.parse(s);
  } catch {
    return {};
  }
}
