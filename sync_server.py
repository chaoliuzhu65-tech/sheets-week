#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
德胧报表 - 轻量级数据同步API服务
功能: 多租户数据存储 + 跨设备读取 (替代 Cloudflare Worker)
部署: 腾讯云轻量服务器 Python 3.8+
端口: 5001 (默认)
"""

import os
import json
import logging
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS

# ── 日志 ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger(__name__)

# ── Flask 初始化 ───────────────────────────────────────────────
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})  # 允许跨域

# ── 数据存储目录 ───────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sync_data')
os.makedirs(DATA_DIR, exist_ok=True)

MAX_BODY_MB = 50  # 最大请求体 50MB


def tenant_file(tenant_id: str) -> str:
    """返回租户数据文件路径（过滤危险字符）"""
    safe_id = ''.join(c for c in tenant_id if c.isalnum() or c in '_-')[:40]
    return os.path.join(DATA_DIR, f'{safe_id}.json')


# ── API 路由 ──────────────────────────────────────────────────

@app.route('/', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'service': '德胧报表同步服务',
        'time': datetime.now().isoformat()
    })


@app.route('/api/sync', methods=['POST', 'OPTIONS'])
def sync_data():
    """前端 → 云端：存储分析结果"""
    if request.method == 'OPTIONS':
        return _cors_preflight()

    tenant = request.args.get('tenant', '').strip()
    if not tenant or len(tenant) < 4:
        return jsonify({'success': False, 'error': '缺少 tenant 参数'}), 400

    # 检查请求大小
    content_length = request.content_length or 0
    if content_length > MAX_BODY_MB * 1024 * 1024:
        return jsonify({'success': False, 'error': '数据过大'}), 413

    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({'success': False, 'error': '请求体不是有效 JSON'}), 400

        # 写入文件
        fpath = tenant_file(tenant)
        data['_sync_time'] = datetime.now().isoformat()
        data['_tenant'] = tenant

        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)

        logger.info(f'同步成功 tenant={tenant} size={os.path.getsize(fpath)}B')
        return jsonify({'success': True, 'message': '同步成功', 'tenant': tenant})

    except Exception as e:
        logger.error(f'同步失败 tenant={tenant} err={e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/last-analysis', methods=['GET', 'OPTIONS'])
def last_analysis():
    """云端 → 前端：读取分析结果（跨设备）"""
    if request.method == 'OPTIONS':
        return _cors_preflight()

    tenant = request.args.get('tenant', '').strip()
    if not tenant or len(tenant) < 4:
        return jsonify({'success': False, 'error': '缺少 tenant 参数'}), 400

    fpath = tenant_file(tenant)
    if not os.path.exists(fpath):
        logger.info(f'云端无数据 tenant={tenant}')
        return jsonify({'success': False, 'error': f'云端无此用户数据: {tenant}'}), 404

    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f'读取成功 tenant={tenant}')
        return jsonify({'success': True, 'analysis': data})
    except Exception as e:
        logger.error(f'读取失败 tenant={tenant} err={e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/tenants', methods=['GET'])
def list_tenants():
    """列出所有已同步的用户（管理用）"""
    secret = request.args.get('secret', '')
    admin_secret = os.getenv('ADMIN_SECRET', 'delong2024admin')
    if secret != admin_secret:
        return jsonify({'error': '需要管理员密钥'}), 403

    files = [f for f in os.listdir(DATA_DIR) if f.endswith('.json')]
    tenants = []
    for fname in files:
        fpath = os.path.join(DATA_DIR, fname)
        stat = os.stat(fpath)
        tenants.append({
            'tenant': fname[:-5],
            'size_kb': round(stat.st_size / 1024, 1),
            'updated': datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    tenants.sort(key=lambda x: x['updated'], reverse=True)
    return jsonify({'success': True, 'count': len(tenants), 'tenants': tenants})


def _cors_preflight():
    resp = jsonify({'ok': True})
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return resp, 200


# ── CORS 响应头 ────────────────────────────────────────────────
@app.after_request
def add_cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp


if __name__ == '__main__':
    port = int(os.getenv('SYNC_PORT', 443))
    logger.info(f'同步服务启动，端口: {port}')
    app.run(host='0.0.0.0', port=port, debug=False)
