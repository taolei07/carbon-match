import random
import streamlit as st
from supabase import create_client, Client
from streamlit_autorefresh import st_autorefresh

# ============================================================
# 页面基本设置
# ============================================================
st.set_page_config(
    page_title="Carbon Match: 碳对决（联机版）", layout="wide"
)

TABLE = "carbon_match_games"


# ============================================================
# Supabase 连接（数据库是双方共享状态的地方）
# ============================================================
@st.cache_resource
def get_supabase() -> Client:
  url = st.secrets["supabase_url"]
  key = st.secrets["supabase_key"]
  return create_client(url, key)


supabase = get_supabase()


def new_deck():
  deck = []
  for num in range(1, 6):
    for _ in range(2):
      deck.append([str(num), "B"])
      deck.append([str(num), "R"])
  for _ in range(4):
    deck.append(["J", "T"])
    deck.append(["A", "T"])
    deck.append(["Q", "T"])
    deck.append(["K", "T"])
  for _ in range(2):
    deck.append(["JOKER", "C"])
  random.shuffle(deck)
  return deck


def initial_state():
  return {
      "deck": new_deck(),
      "ap": 2,
      "turn": "玩家 1",
      "p1_staging": [],
      "p1_scoring": [],
      "p1_hand": [],
      "p1_score": 0.0,
      "p2_staging": [],
      "p2_scoring": [],
      "p2_hand": [],
      "p2_score": 0.0,
      "active_tactical": None,
      "tactical_hand_idx": None,
      "tactical_player": None,
      "q_selected_own_card": None,
      "game_over": False,
      "logs": ["🎮 游戏开始！双人碳中和竞赛启动，当前为 玩家 1 回合。"],
  }


def load_game(room_code):
  res = supabase.table(TABLE).select("*").eq("room_code", room_code).execute()
  if res.data:
    return res.data[0]["state"]
  state = initial_state()
  supabase.table(TABLE).insert(
      {"room_code": room_code, "state": state}
  ).execute()
  return state


def save_game(room_code, state):
  supabase.table(TABLE).update({"state": state}).eq(
      "room_code", room_code
  ).execute()


def add_log(state, msg):
  state["logs"].insert(0, msg)
  if len(state["logs"]) > 200:
    state["logs"].pop()


def check_game_over_and_settle(state):
  if len(state["deck"]) == 0 and not state["game_over"]:
    p1_has_power = any(
        c[0] in ["J", "A", "Q", "K", "JOKER"] for c in state["p1_hand"]
    )
    p2_has_power = any(
        c[0] in ["J", "A", "Q", "K", "JOKER"] for c in state["p2_hand"]
    )
    if not p1_has_power and not p2_has_power:
      state["game_over"] = True
      p1_s = state["p1_score"]
      p2_s = state["p2_score"]
      if p1_s > p2_s:
        winner = "玩家 1"
      elif p2_s > p1_s:
        winner = "玩家 2"
      else:
        winner = "平局"
      add_log(
          state,
          f"🏁 【游戏结束】最终结算：玩家1 得分 {p1_s}，玩家2 得分"
          f" {p2_s}。恭喜【{winner}】获胜！",
      )


def check_auto_same_color_match(state, is_p1):
  staging = state["p1_staging"] if is_p1 else state["p2_staging"]
  scoring = state["p1_scoring"] if is_p1 else state["p2_scoring"]
  p_name = "玩家 1" if is_p1 else "玩家 2"

  if len(staging) >= 2:
    vals = [c[0] for c in staging if c[1] in ["B", "R"]]
    for v in set(vals):
      mc = [c for c in staging if c[0] == v and c[1] in ["B", "R"]]
      for color in ["B", "R"]:
        color_cards = [c for c in mc if c[1] == color]
        if len(color_cards) >= 2:
          c1, c2 = color_cards[0], color_cards[1]
          num_v = int(v)
          if color == "B":
            pts = -num_v * 1.0
            if is_p1:
              state["p1_score"] += pts
            else:
              state["p2_score"] += pts
            add_log(
                state,
                f"🚨 【强制同色】{p_name} 触发双黑对(数字{v})：计算 -{v} ="
                f" {pts} 分",
            )
          else:
            pts = num_v * 1.5
            if is_p1:
              state["p1_score"] += pts
            else:
              state["p2_score"] += pts
            add_log(
                state,
                f"💡 【强制同色】{p_name} 触发双红对(数字{v})：计算 +{v} * 1.5 ="
                f" +{pts} 分",
            )

          scoring.append([c1, c2])
          new_st = [c for c in staging if c != c1 and c != c2]
          if is_p1:
            state["p1_staging"] = new_st
          else:
            state["p2_staging"] = new_st
          return True
  return False


def auto_joker_transfer(state, is_p1):
  """抽到 JOKER 时自动触发：把自己得分区分数最高的组合送去对方暂存区。"""
  scoring = state["p1_scoring"] if is_p1 else state["p2_scoring"]
  p_name = "玩家 1" if is_p1 else "玩家 2"
  opp_name = "玩家 2" if is_p1 else "玩家 1"

  if not scoring:
    add_log(state, f"🃏 {p_name} 抽到 JOKER，但得分区空空如也，混沌效果落空！")
    return

  best_idx = 0
  best_pts = None
  for idx, item in enumerate(scoring):
    pts = 0.0
    for card in item:
      val_num = int(card[0])
      if card[1] == "B":
        pts += -val_num * 1.0
      elif card[1] == "R":
        pts += val_num * 1.5
    if best_pts is None or pts > best_pts:
      best_pts = pts
      best_idx = idx

  removed_pair = scoring.pop(best_idx)

  if is_p1:
    state["p1_score"] -= best_pts
    state["p2_staging"].extend(removed_pair)
  else:
    state["p2_score"] -= best_pts
    state["p1_staging"].extend(removed_pair)

  add_log(
      state,
      f"🃏 {p_name} 抽到 JOKER！混沌降临：得分区最高分组合 {removed_pair}"
      f"（{best_pts} 分）被自动送去了 {opp_name} 的暂存区！",
  )

  check_auto_same_color_match(state, not is_p1)


def render_card_html(val, card_type, size="normal"):
  if card_type == "J":
    bg, border, text_c, label = "#e3f2fd", "#2196f3", "#0d47a1", "战术(AP+1)"
  elif card_type == "A":
    bg, border, text_c, label = "#f3e5f5", "#ab47bc", "#4a148c", "战术(全暂存互换)"
  elif card_type == "Q":
    bg, border, text_c, label = "#e1f5fe", "#00acc1", "#006064", "战术(单张互换)"
  elif card_type == "K":
    bg, border, text_c, label = "#e8f5e9", "#4caf50", "#1b5e20", "战术(推送)"
  elif card_type == "JOKER":
    bg, border, text_c, label = "#fff3e0", "#ff9800", "#e65100", "混沌小丑"
  elif card_type == "B":
    bg, border, text_c, label = "#f0f2f6", "#333333", "#111111", "黑(排放)"
  elif card_type == "R":
    bg, border, text_c, label = "#ffe6e6", "#ff4b4b", "#c62828", "红(捕集)"
  else:
    bg, border, text_c, label = "#ffffff", "#cccccc", "#333333", ""

  if size == "large":
    w, h, fs, l_fs = "100px", "130px", "32px", "11px"
  elif size == "medium":
    w, h, fs, l_fs = "75px", "95px", "24px", "10px"
  else:
    w, h, fs, l_fs = "55px", "70px", "18px", "8px"

  return f"""
    <div style="width: {w}; height: {h}; border: 3px solid {border}; border-radius: 10px; background-color: {bg}; display: inline-flex; flex-direction: column; align-items: center; justify-content: center; box-shadow: 2px 3px 6px rgba(0,0,0,0.15); margin: 4px; text-align: center;">
        <span style="font-size: {fs}; font-weight: bold; color: {text_c};">{val}</span>
        <span style="font-size: {l_fs}; color: #444; font-weight: bold; margin-top: 2px;">{label}</span>
    </div>
    """


# ============================================================
# 房间 / 身份 选择界面（这部分是每个浏览器自己的，不进数据库）
# ============================================================
if "room_code" not in st.session_state:
  st.session_state.room_code = None
if "my_player_is_p1" not in st.session_state:
  st.session_state.my_player_is_p1 = None

if st.session_state.room_code is None:
  st.title("🃏 Carbon Match：碳对决（联机版）")
  st.caption("和朋友输入同一个房间码，各自选好自己是玩家1还是玩家2，就能联机对战。")

  room_input = st.text_input("房间码（双方需完全一致，自己随便起一个即可，如 abc123）")
  player_choice = st.radio("你是？", ["玩家 1", "玩家 2"], horizontal=True)

  if st.button("加入 / 创建房间", type="primary"):
    if room_input.strip():
      st.session_state.room_code = room_input.strip()
      st.session_state.my_player_is_p1 = player_choice == "玩家 1"
      st.rerun()
    else:
      st.warning("请先输入房间码。")
  st.stop()

room_code = st.session_state.room_code
my_player_is_p1 = st.session_state.my_player_is_p1
my_player_name = "玩家 1" if my_player_is_p1 else "玩家 2"

# 每 2.5 秒自动刷新一次，这样对方的操作不用手动刷新页面也能看到
st_autorefresh(interval=2500, key="auto_refresh")

state = load_game(room_code)

# ============================================================
# 界面头部
# ============================================================
top_l, top_r = st.columns([4, 1])
with top_l:
  st.title("🃏 Carbon Match: 碳对决（联机版）")
  st.caption(
      f"房间：{room_code} ｜ 你是：{my_player_name} ｜ "
      "规则：J无条件+1AP；A消耗1AP全暂存互换；Q消耗1AP单张精准互换；K推送；抽到JOKER自动送出最高分组合。"
  )
with top_r:
  if st.button("🚪 离开房间"):
    st.session_state.room_code = None
    st.session_state.my_player_is_p1 = None
    st.rerun()

# 当前回合是否轮到"这个浏览器所代表的玩家"来操作
can_act = (state["turn"] == my_player_name) and not state["game_over"]

deck_count = len(state["deck"])
st.markdown(
    f"""
    <div style="background: linear-gradient(135deg, #2c3e50, #4ca1af); padding: 14px; border-radius: 12px; text-align: center; color: white; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
        <h3 style="margin: 0; font-size: 22px;">📦 核心牌堆状态</h3>
        <p style="margin: 6px 0 0 0; font-size: 26px; font-weight: bold; color: #f1c40f;">剩余牌数: {deck_count} / 38 张</p>
    </div>
    """,
    unsafe_allow_html=True,
)

top1, top2, top3, top4 = st.columns(4)
top1.metric("📍 当前回合", state["turn"])
top2.metric("⚡ 当前行动点", f"{state['ap']} / 2")
top3.metric(
    "⭐ 比分", f"P1: {state['p1_score']} | P2: {state['p2_score']}"
)
if top4.button("🔄 重新开始本局", use_container_width=True):
  save_game(room_code, initial_state())
  st.rerun()

st.markdown("---")


# ============================================================
# 左右分屏架构
# ============================================================
col_p1, col_p2 = st.columns(2)


def render_player_column(target_is_p1):
  p_name = "玩家 1" if target_is_p1 else "玩家 2"
  is_mine = target_is_p1 == my_player_is_p1
  turn_is_this_player = (state["turn"] == p_name) and not state["game_over"]
  score = state["p1_score"] if target_is_p1 else state["p2_score"]
  staging = state["p1_staging"] if target_is_p1 else state["p2_staging"]
  scoring = state["p1_scoring"] if target_is_p1 else state["p2_scoring"]
  hand = state["p1_hand"] if target_is_p1 else state["p2_hand"]

  with st.container():
    label = "🔵 玩家 1 专区" if target_is_p1 else "🔴 玩家 2 专区"
    if is_mine:
      label += "（你）"
    st.markdown(f"### {label}")

    if turn_is_this_player:
      if is_mine:
        st.success(f"⚡ 轮到你操作 (剩余 AP: {state['ap']})")
      else:
        st.info("⏳ 轮到对方操作，请稍候…")
    else:
      st.caption(f"（当前得分: {score}）")

    if is_mine and can_act:
      b1, b2, b3 = st.columns(3)
      with b1:
        if st.button("🎴 抽牌 (-1 AP)", key=f"draw_{p_name}"):
          if state["ap"] > 0 and len(state["deck"]) > 0:
            card = state["deck"].pop(0)
            state["ap"] -= 1
            if card[1] in ["B", "R"]:
              staging.append(card)
              add_log(state, f"{p_name} 抽到数字牌【{card[0]}-{card[1]}】，入暂存区。")
              check_auto_same_color_match(state, target_is_p1)
            elif card[0] == "JOKER":
              add_log(state, f"{p_name} 抽到了 JOKER！")
              auto_joker_transfer(state, target_is_p1)
            else:
              hand.append(card)
              add_log(state, f"{p_name} 抽到战术手牌【{card[0]}】。")
            check_game_over_and_settle(state)
            save_game(room_code, state)
            st.rerun()
          else:
            st.warning("行动点不足或牌堆空！")
      with b2:
        if st.button("🌿 异色对碳中和(0分)", key=f"neutral_{p_name}"):
          if len(staging) >= 2:
            vals = [c[0] for c in staging if c[1] in ["B", "R"]]
            matched = False
            for v in set(vals):
              mc = [c for c in staging if c[0] == v and c[1] in ["B", "R"]]
              b_cards = [c for c in mc if c[1] == "B"]
              r_cards = [c for c in mc if c[1] == "R"]
              if b_cards and r_cards:
                c1, c2 = b_cards[0], r_cards[0]
                scoring.append([c1, c2])
                staging.remove(c1)
                staging.remove(c2)
                add_log(state, f"🌿 {p_name} 自主结算【绝对碳中和】混合对 (数字 {v})：0 分。")
                matched = True
                break
            if matched:
              save_game(room_code, state)
              st.rerun()
            else:
              st.warning("暂存区没有可配对的异色牌！")
          else:
            st.warning("暂存区牌数少于2张！")
      with b3:
        if st.button("⏭️ 结束回合", key=f"end_{p_name}"):
          state["ap"] = 2
          state["turn"] = "玩家 2" if target_is_p1 else "玩家 1"
          state["active_tactical"] = None
          state["tactical_player"] = None
          state["q_selected_own_card"] = None
          add_log(state, f"轮次交替：当前轮到 {state['turn']}。")
          save_game(room_code, state)
          st.rerun()

    st.markdown("---")

    # --- 1. 手牌库 ---
    st.markdown(f"**🎒 {p_name} 的手牌库**")
    if hand:
      h_cols = st.columns(len(hand) if len(hand) <= 4 else 4)
      for h_idx, hcard in enumerate(hand):
        with h_cols[h_idx % 4]:
          st.markdown(
              render_card_html(hcard[0], hcard[0], size="large"),
              unsafe_allow_html=True,
          )
          if is_mine and can_act:
            if st.button(f"打出 #{h_idx+1}", key=f"play_{p_name}_{h_idx}"):
              ctype = hcard[0]
              if ctype == "J":
                hand.pop(h_idx)
                state["ap"] += 1
                add_log(state, f"⚡ {p_name} 打出 J 卡：获得 +1 额外行动点！")
                check_game_over_and_settle(state)
                save_game(room_code, state)
                st.rerun()
              elif ctype == "A":
                if state["ap"] > 0:
                  hand.pop(h_idx)
                  state["ap"] -= 1
                  state["p1_staging"], state["p2_staging"] = (
                      state["p2_staging"],
                      state["p1_staging"],
                  )
                  add_log(state, f"🔄 {p_name} 打出 A 卡：双方暂存区整体互换！")
                  check_auto_same_color_match(state, True)
                  check_auto_same_color_match(state, False)
                  check_game_over_and_settle(state)
                  save_game(room_code, state)
                  st.rerun()
                else:
                  st.warning("⚠️ 行动点(AP)不足，无法使用 A 卡！")
              elif ctype == "Q":
                if state["ap"] > 0:
                  state["active_tactical"] = "Q"
                  state["tactical_hand_idx"] = h_idx
                  state["tactical_player"] = target_is_p1
                  state["q_selected_own_card"] = None
                  add_log(state, f"🎯 {p_name} 准备打出 Q 卡：请先选自己暂存区的一张牌。")
                  save_game(room_code, state)
                  st.rerun()
                else:
                  st.warning("⚠️ 行动点(AP)不足，无法使用 Q 卡！")
              elif ctype == "K":
                if state["ap"] > 0:
                  state["active_tactical"] = "K"
                  state["tactical_hand_idx"] = h_idx
                  state["tactical_player"] = target_is_p1
                  add_log(state, f"🎯 {p_name} 准备打出 K 卡：请选暂存区要推给对手的一张牌。")
                  save_game(room_code, state)
                  st.rerun()
                else:
                  st.warning("⚠️ 行动点(AP)不足，无法使用 K 卡！")
    else:
      st.caption("手牌库为空")

    st.markdown("---")

    # --- 2. 暂存区 ---
    st.markdown(f"**📥 {p_name} 的暂存区**")
    if (
        state["active_tactical"] == "K"
        and can_act
        and target_is_p1 == state["tactical_player"]
    ):
      st.info("👉 【K卡生效中】请点击下方暂存区中想“推送给对手”的那张牌：")
    elif state["active_tactical"] == "Q" and can_act:
      if state["q_selected_own_card"] is None:
        if target_is_p1 == state["tactical_player"]:
          st.info("👉 【Q卡生效中】请先在自己的暂存区选择一张要互换的牌：")
      else:
        if target_is_p1 != state["tactical_player"]:
          st.info("👉 【Q卡生效中】请在对方暂存区点击一张牌完成互换：")

    if staging:
      st_cols = st.columns(len(staging) if len(staging) <= 4 else 4)
      for idx, card in enumerate(staging):
        with st_cols[idx % 4]:
          st.markdown(
              render_card_html(card[0], card[1], size="medium"),
              unsafe_allow_html=True,
          )

          if (
              state["active_tactical"] == "K"
              and can_act
              and target_is_p1 == state["tactical_player"]
          ):
            if st.button(f"推这张 #{idx+1}", key=f"push_k_{target_is_p1}_{idx}"):
              h_idx = state["tactical_hand_idx"]
              (state["p1_hand"] if target_is_p1 else state["p2_hand"]).pop(
                  h_idx
              )
              state["ap"] -= 1
              pushed_card = staging.pop(idx)
              if target_is_p1:
                state["p2_staging"].append(pushed_card)
                add_log(state, f"🎯 玩家 1 使用 K 卡：推送 {pushed_card} 给了 玩家 2！")
                check_auto_same_color_match(state, False)
              else:
                state["p1_staging"].append(pushed_card)
                add_log(state, f"🎯 玩家 2 使用 K 卡：推送 {pushed_card} 给了 玩家 1！")
                check_auto_same_color_match(state, True)

              state["active_tactical"] = None
              state["tactical_hand_idx"] = None
              state["tactical_player"] = None
              check_game_over_and_settle(state)
              save_game(room_code, state)
              st.rerun()

          elif (
              state["active_tactical"] == "Q"
              and can_act
              and state["q_selected_own_card"] is None
          ):
            if target_is_p1 == state["tactical_player"]:
              if st.button(f"选这张 #{idx+1}", key=f"q_own_{target_is_p1}_{idx}"):
                state["q_selected_own_card"] = [target_is_p1, idx, card]
                add_log(state, f"🔄 {p_name} 已锁定自己的牌 {card}，请点对方暂存区完成互换。")
                save_game(room_code, state)
                st.rerun()

          elif (
              state["active_tactical"] == "Q"
              and can_act
              and state["q_selected_own_card"] is not None
          ):
            if target_is_p1 != state["tactical_player"]:
              if st.button(f"换这张 #{idx+1}", key=f"q_target_{target_is_p1}_{idx}"):
                own_p_is_p1, own_idx, own_card = state["q_selected_own_card"]
                h_idx = state["tactical_hand_idx"]
                (
                    state["p1_hand"] if own_p_is_p1 else state["p2_hand"]
                ).pop(h_idx)
                state["ap"] -= 1

                target_card = staging[idx]

                if own_p_is_p1:
                  state["p1_staging"][own_idx] = target_card
                  state["p2_staging"][idx] = own_card
                  add_log(
                      state,
                      f"🔄 玩家 1 使用 Q 卡：{own_card} 与 玩家2 的 {target_card} 互换！",
                  )
                else:
                  state["p2_staging"][own_idx] = target_card
                  state["p1_staging"][idx] = own_card
                  add_log(
                      state,
                      f"🔄 玩家 2 使用 Q 卡：{own_card} 与 玩家1 的 {target_card} 互换！",
                  )

                state["active_tactical"] = None
                state["tactical_hand_idx"] = None
                state["tactical_player"] = None
                state["q_selected_own_card"] = None

                check_auto_same_color_match(state, True)
                check_auto_same_color_match(state, False)
                check_game_over_and_settle(state)
                save_game(room_code, state)
                st.rerun()
    else:
      st.caption("暂存区空")

    st.markdown("---")

    # --- 3. 得分区 ---
    st.markdown(f"**🏆 {p_name} 得分区 (总分: {score})**")
    if scoring:
      for idx, s_item in enumerate(scoring):
        st.markdown(
            f"<span style='font-size:14px;'>组合 #{idx+1}</span>",
            unsafe_allow_html=True,
        )
        if len(s_item) == 2:
          sc1, sc2 = st.columns(2)
          with sc1:
            st.markdown(
                render_card_html(s_item[0][0], s_item[0][1], size="small"),
                unsafe_allow_html=True,
            )
          with sc2:
            st.markdown(
                render_card_html(s_item[1][0], s_item[1][1], size="small"),
                unsafe_allow_html=True,
            )
        else:
          st.markdown(
              render_card_html(s_item[0][0], s_item[0][1], size="small"),
              unsafe_allow_html=True,
          )
    else:
      st.caption("得分区暂无对子")


with col_p1:
  render_player_column(True)

with col_p2:
  render_player_column(False)

st.markdown("---")
st.subheader("📋 游戏动态日志")
log_container = st.container(height=180)
with log_container:
  for lg in state["logs"]:
    st.markdown(f"- {lg}")
