#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ABC球大小预测模型 - 200个"""

import random
from collections import Counter

def abc_big_small_predict(history_data, cfg, ball_type):
    if not history_data or len(history_data) < 10:
        return random.choice(['大', '小'])
    try:
        size_history = []
        target_map = {'A': 0, 'B': 1, 'C': 2}
        t = target_map[ball_type]
        for item in history_data[:cfg['depth']]:
            total = item.get('sum', 0)
            s = str(total).zfill(2)
            a = int(s[-2]) if len(s) >= 2 else 0
            b = int(s[-1])
            c = (total % 10)
            num = [a, b, c][t]
            size_history.append('大' if num >= 5 else '小')
        if not size_history:
            return random.choice(['大', '小'])
        if cfg['type'] == 'FREQ':
            counts = Counter(size_history)
            return max(counts, key=counts.get)
        elif cfg['type'] == 'TREND':
            recent = size_history[:cfg['trend_len']]
            if len(recent) >= 2:
                return '大' if recent[0] == '小' else '小'
            return recent[0] if recent else random.choice(['大', '小'])
        elif cfg['type'] == 'GAP':
            for sz in ['大', '小']:
                if sz not in size_history:
                    return sz
            return random.choice(['大', '小'])
        elif cfg['type'] == 'WAVE':
            qihao = int(history_data[0].get('nbr', 1)) if str(history_data[0].get('nbr', '')).isdigit() else 1
            seed = (qihao * cfg['wave_m'] + cfg['wave_s']) % 2
            return '大' if seed == 1 else '小'
        elif cfg['type'] == 'COMBO':
            total = history_data[0].get('sum', 0)
            s = str(total).zfill(2)
            a = int(s[-2]) if len(s) >= 2 else 0
            b = int(s[-1])
            if ball_type == 'A': return '大' if b >= 5 else '小'
            elif ball_type == 'B': return '大' if a >= 5 else '小'
            else: return '大' if (a + b) >= 9 else '小'
        return random.choice(['大', '小'])
    except:
        return random.choice(['大', '小'])

ABC_SIZE_MODELS = {}
ball_names = {'A': 'A球', 'B': 'B球', 'C': 'C球'}
model_id = 4001
for ball in ['A', 'B', 'C']:
    for i in range(1, 68):
        if model_id > 4200: break
        if i <= 15:
            cfg = {'type': 'FREQ', 'depth': 10 + (i % 20), 'ball': ball}
        elif i <= 30:
            cfg = {'type': 'TREND', 'depth': 8 + (i % 15), 'trend_len': 3 + (i % 5), 'ball': ball}
        elif i <= 45:
            cfg = {'type': 'GAP', 'depth': 12 + (i % 25), 'ball': ball}
        elif i <= 55:
            cfg = {'type': 'WAVE', 'depth': 10, 'wave_m': (i * 7) % 13 + 1, 'wave_s': i % 5, 'ball': ball}
        else:
            cfg = {'type': 'COMBO', 'depth': 5, 'ball': ball}
        def make_predictor(c=cfg, b=ball):
            return lambda h: abc_big_small_predict(h, c, b)
        ABC_SIZE_MODELS[model_id] = {
            'func': make_predictor(),
            'info': {'id': model_id, 'name': f'{ball_names[ball]}大小预测 M{model_id}', 'ball': ball, 'type': cfg['type']}
        }
        model_id += 1

class ABCSizeModelManager:
    def __init__(self):
        self.models = ABC_SIZE_MODELS
    def get_best_model(self, history, ball_type):
        if not history or len(history) < 10: return '大', 0, 0
        results = []
        total = min(100, len(history) - 1)
        target_map = {'A': 0, 'B': 1, 'C': 2}
        t = target_map[ball_type]
        for mid, md in self.models.items():
            if md['info']['ball'] != ball_type: continue
            win = 0
            for i in range(1, total):
                try:
                    pred = md['func'](history[i:])
                    actual_total = history[i-1].get('sum', 0)
                    s = str(actual_total).zfill(2)
                    a = int(s[-2]) if len(s) >= 2 else 0
                    b = int(s[-1])
                    c = (actual_total % 10)
                    num = [a, b, c][t]
                    actual = '大' if num >= 5 else '小'
                    if pred == actual: win += 1
                except: continue
            rate = win / total if total > 0 else 0
            results.append((mid, rate, md['func'](history)))
        results.sort(key=lambda x: x[1], reverse=True)
        top3 = results[:3]
        best = random.choice(top3)
        return best[2], best[1], best[0]
    def get_all_predictions(self, history):
        result = {}
        for ball in ['A', 'B', 'C']:
            pred, rate, mid = self.get_best_model(history, ball)
            result[ball] = {'prediction': pred, 'win_rate': round(rate * 100, 1), 'model_id': mid}
        return result
