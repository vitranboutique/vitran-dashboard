"""fix_missing_addr_phone.py — Thêm SĐT vào ĐỊA CHỈ cho khách 'thiếu SĐT ở địa chỉ'.

An toàn: chỉ PUT trường phone qua /admin/customers/{cid}/addresses/{aid}.json
(partial update — giữ nguyên address1/mã vùng, kể cả dữ liệu bị che). Idempotent:
chạy lại chỉ đụng khách còn thiếu.

Điều kiện fix: default_address có province_code, KHÔNG có phone, và khách CÓ SĐT liên hệ.
"""
import os, re, time, json, requests
s = requests.Session()
s.headers.update({'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json', 'Content-Type': 'application/json'})
s.auth = (os.environ['SAPO_API_KEY'], os.environ['SAPO_API_SECRET'])
B = 'https://vitranboutiquehcm.mysapo.net'


def canon(p):
    if '*' in str(p or ''):
        return ''
    d = re.sub(r'\D', '', str(p or ''))
    if d.startswith('00'):
        d = d[2:]
    if d.startswith('84') and len(d) == 11:
        d = '0' + d[2:]
    d = '0' + d.lstrip('0')
    return d if len(d) == 10 else ''


def getp(page):
    for attempt in range(4):
        try:
            r = s.get(f'{B}/admin/customers.json', params={'limit': 250, 'page': page}, timeout=40)
            if r.status_code == 429:
                time.sleep(2 * (attempt + 1)); continue
            return r.json().get('customers') or []
        except Exception:
            time.sleep(1.5)
    return []


ok = fail = seen = 0
fail_ids = []
for page in range(1, 200):
    custs = getp(page)
    if not custs:
        break
    for c in custs:
        a = c.get('default_address') or (c.get('addresses') or [None])[0]
        if not a:
            continue
        pc = str(a.get('province_code') or '').strip()
        ph = str(a.get('phone') or a.get('phone_number') or a.get('mobile') or '').strip()
        if not pc or ph:
            continue                      # đã chuẩn hoặc là nhóm khác
        newphone = canon(c.get('phone'))
        if not newphone:
            continue                      # không có SĐT liên hệ để thêm
        seen += 1
        cid, aid = c.get('id'), a.get('id')
        done = False
        for attempt in range(3):
            try:
                r = s.put(f'{B}/admin/customers/{cid}/addresses/{aid}.json',
                          data=json.dumps({'address': {'phone': newphone, 'phone_number': newphone, 'mobile': newphone}}),
                          timeout=30)
                if r.status_code == 429:
                    time.sleep(2 * (attempt + 1)); continue
                done = r.status_code < 400
                break
            except Exception:
                time.sleep(1.5)
        if done:
            ok += 1
        else:
            fail += 1; fail_ids.append(cid)
        if seen % 50 == 0:
            print(f'  ... đã xử lý {seen} | ok {ok} | lỗi {fail}', flush=True)
        time.sleep(0.4)
    if len(custs) < 250:
        break
print(f'XONG: thêm SĐT cho {ok} khách, lỗi {fail}. (mã lỗi: {fail_ids[:20]})', flush=True)
print('DONE', flush=True)
