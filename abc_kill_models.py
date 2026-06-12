import random

ABC_KILL_MODELS = {}

def create_predictor(depth, offset, weight, formula_type):
    def predictor(history_balls):
        if len(history_balls) < depth:
            return (offset) % 10
        segment = history_balls[:depth]
        if formula_type == 0:
            core_val = sum(val * (weight + idx) for idx, val in enumerate(segment))
        elif formula_type == 1:
            core_val = sum(abs(segment[i] - segment[i + 1]) * weight for i in range(len(segment) - 1))
        else:
            core_val = 1
            for val in segment:
                core_val *= val + 1
            core_val *= weight
        return int(core_val + offset) % 10
    return predictor

random.seed(42)
ball_types = ["A", "B", "C"]

for ball in ball_types:
    for i in range(1, 101):
        model_id = f"Model_{ball}_{i:03d}"
        depth = random.randint(3, 15)
        offset = random.randint(0, 9)
        weight = random.uniform(0.5, 5.0)
        formula_type = random.randint(0, 2)
        predictor = create_predictor(depth, offset, weight, formula_type)
        ABC_KILL_MODELS[model_id] = {"func": predictor, "ball": ball}

class ABCKillModelManager:
    @staticmethod
    def get_best_model(history, ball_type):
        ball_index = {"A": 0, "B": 1, "C": 2}[ball_type]
        ball_history = []
        for item in history:
            parts = list(map(int, item["number"].split("+")))
            ball_history.append(parts[ball_index])
        if not ball_history:
            return None, 0, 0.0, []
        model_win_rates = []
        target_models = {m_id: info for m_id, info in ABC_KILL_MODELS.items() if info["ball"] == ball_type}
        total_len = len(ball_history)
        for m_id, info in target_models.items():
            predictor_func = info["func"]
            success_count = 0
            test_count = 0
            for i in range(total_len - 1):
                sub_history = ball_history[i + 1:]
                actual_num = ball_history[i]
                pred_kill = predictor_func(sub_history)
                if actual_num != pred_kill:
                    success_count += 1
                test_count += 1
                if test_count >= 100:
                    break
            win_rate = success_count / test_count if test_count > 0 else 0.0
            model_win_rates.append((m_id, win_rate))
        model_win_rates.sort(key=lambda x: x[1], reverse=True)
        top_5 = model_win_rates[:5]
        chosen_model_id, chosen_win_rate = random.choice(top_5)
        final_kill = ABC_KILL_MODELS[chosen_model_id]["func"](ball_history)
        return chosen_model_id, final_kill, chosen_win_rate, top_5

    @classmethod
    def get_all_predictions(cls, history):
        results = {}
        for ball in ["A", "B", "C"]:
            chosen_id, kill_num, win_rate, top_5 = cls.get_best_model(history, ball)
            bet_numbers = [num for num in range(10) if num != kill_num]
            results[ball] = {
                "model_id": chosen_id,
                "win_rate": win_rate,
                "kill_num": kill_num,
                "bet_numbers": bet_numbers,
            }
        return results
