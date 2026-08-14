import random
import streamlit as str_lit
import streamlit as st
from supabase import create_client, Client
from streamlit_autorefresh import st_autorefresh

# ============================================================
# Page Setup
# ============================================================
st.set_page_config(
    page_title="Carbon Match: Carbon Showdown (Online)", layout="wide"
)

TABLE = "carbon_match_games"


# ============================================================
# Supabase Connection
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
        "turn": "Player 1",
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
        "logs": ["🎮 Game started! Carbon neutrality dual match launched. Player 1's turn."],
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
    if len(state["logs"]) > 2000:
        state["logs"].pop()


def check_game_over_and_settle(state):
    if len(state["deck"]) == 0 and not state["game_over"]:
        p1_has_power = any(
            c[0] in ["J", "A", "Q", "K", "JOKER"] for c in state["p1_hand"]
        )
        p2_has_power = any(
            c[0] in ["J", "A", "Q", "K", "JOKER"] for c in state["p2_hand"]
        )
        
        both_staging_empty = (len(state["p1_staging"]) == 0) and (len(state["p2_staging"]) == 0)

        if (not p1_has_power and not p2_has_power) or both_staging_empty:
            state["game_over"] = True
            p1_s = state["p1_score"]
            p2_s = state["p2_score"]
            if p1_s > p2_s:
                winner = "Player 1"
            elif p2_s > p1_s:
                winner = "Player 2"
            else:
                winner = "Draw"
            add_log(
                state,
                f"🏁 【Game Over】Final Settlement: Player 1 Score {p1_s}, Player 2 Score {p2_s}. Winner: [{winner}]!",
            )


def check_auto_same_color_match(state, is_p1):
    staging = state["p1_staging"] if is_p1 else state["p2_staging"]
    scoring = state["p1_scoring"] if is_p1 else state["p2_scoring"]
    p_name = "Player 1" if is_p1 else "Player 2"

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
                            f"🚨 {p_name} triggered Double Black Pair (No.{v}): -{v} = {pts} pts",
                        )
                    else:
                        pts = num_v * 1.5
                        if is_p1:
                            state["p1_score"] += pts
                        else:
                            state["p2_score"] += pts
                        add_log(
                            state,
                            f"💡 {p_name} triggered Double Red Pair (No.{v}): +{v} * 1.5 = +{pts} pts",
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
    scoring = state["p1_scoring"] if is_p1 else state["p2_scoring"]
    p_name = "Player 1" if is_p1 else "Player 2"
    opp_name = "Player 2" if is_p1 else "Player 1"

    st.balloons()
    st.toast(f"🃏 {p_name} drew JOKER! Chaos triggered!", icon="🃏")

    if not scoring:
        add_log(state, f"🃏 {p_name} drew a JOKER, but the scoring area is empty, chaos effect fails!")
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
        f"🃏 {p_name} drew a JOKER! Highest scoring pair {removed_pair} ({best_pts} pts) sent to {opp_name}'s staging area!",
    )

    check_auto_same_color_match(state, not is_p1)


def render_card_html(val, card_type, size="normal"):
    if card_type == "J":
        bg, border, text_c, label = "#e3f2fd", "#2196f3", "#0d47a1", "Tactical (AP+1)"
    elif card_type == "A":
        bg, border, text_c, label = "#f3e5f5", "#ab47bc", "#4a148c", "Tactical (All Swap)"
    elif card_type == "Q":
        bg, border, text_c, label = "#e1f5fe", "#00acc1", "#006064", "Tactical (Single Swap)"
    elif card_type == "K":
        bg, border, text_c, label = "#e8f5e9", "#4caf50", "#1b5e20", "Tactical (Push)"
    elif card_type == "JOKER":
        bg, border, text_c, label = "#fff3e0", "#ff9800", "#e65100", "Chaos Jester"
    elif card_type == "B":
        bg, border, text_c, label = "#f0f2f6", "#333333", "#111111", "Black (Emission)"
    elif card_type == "R":
        bg, border, text_c, label = "#ffe6e6", "#ff4b4b", "#c62828", "Red (Capture)"
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
# Room Selection
# ============================================================
if "room_code" not in st.session_state:
    st.session_state.room_code = None
if "my_player_is_p1" not in st.session_state:
    st.session_state.my_player_is_p1 = None

if st.session_state.room_code is None:
    st.title("🃏 Carbon Match: Carbon Showdown (Online)")
    st.caption("Enter the same room code with your opponent, choose your role, and battle online.")

    room_input = st.text_input("Room Code (Must match opponent, e.g., abc123)")
    player_choice = st.radio("You are?", ["Player 1", "Player 2"], horizontal=True)

    if st.button("Join / Create Room", type="primary"):
        if room_input.strip():
            st.session_state.room_code = room_input.strip()
            st.session_state.my_player_is_p1 = player_choice == "Player 1"
            st.rerun()
        else:
            st.warning("Please enter a room code first.")
    st.stop()

room_code = st.session_state.room_code
my_player_is_p1 = st.session_state.my_player_is_p1
my_player_name = "Player 1" if my_player_is_p1 else "Player 2"

st_autorefresh(interval=2500, key="auto_refresh")

state = load_game(room_code)

# ============================================================
# Header Layout
# ============================================================
top_l, top_r = st.columns([4, 1])
with top_l:
    st.title("🃏 Carbon Match: Carbon Showdown (Online)")
    st.caption(
        f"Room: {room_code} ｜ You are: {my_player_name} ｜ "
        "Rules: J (+1AP); A (All Staging Swap); Q (Single Swap); K (Push); JOKER (Auto Transfer Highest Score Pair)."
    )
with top_r:
    if st.button("🚪 Leave Room"):
        st.session_state.room_code = None
        st.session_state.my_player_is_p1 = None
        st.rerun()

can_act = (state["turn"] == my_player_name) and not state["game_over"]

deck_count = len(state["deck"])
st.markdown(
    f"""
    <div style="background: linear-gradient(135deg, #2c3e50, #4ca1af); padding: 14px; border-radius: 12px; text-align: center; color: white; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
        <h3 style="margin: 0; font-size: 22px;">📦 Deck Status</h3>
        <p style="margin: 6px 0 0 0; font-size: 26px; font-weight: bold; color: #f1c40f;">Cards Remaining: {deck_count} / 38</p>
    </div>
    """,
    unsafe_allow_html=True,
)

top1, top2, top3, top4 = st.columns(4)
top1.metric("📍 Current Turn", state["turn"])
top2.metric("⚡ Current AP", f"{state['ap']} / 2")
top3.metric(
    "⭐ Score", f"P1: {state['p1_score']} | P2: {state['p2_score']}"
)
if top4.button("🔄 Restart Game", use_container_width=True):
    save_game(room_code, initial_state())
    st.rerun()

# ============================================================
# Game Over Popup Banner (新增炫酷胜利弹窗效果字)
# ============================================================
if state["game_over"]:
    p1_s = state["p1_score"]
    p2_s = state["p2_score"]
    if p1_s > p2_s:
        winner_text = "Player 1"
        winner_score = p1_s
    elif p2_s > p1_s:
        winner_text = "Player 2"
        winner_score = p2_s
    else:
        winner_text = "Draw (Tie Game)"
        winner_score = f"P1: {p1_s} / P2: {p2_s}"

    st.markdown(
        f"""
        <div style="background: linear-gradient(135deg, #f12711, #f5af19); padding: 25px; border-radius: 15px; text-align: center; color: white; margin-bottom: 25px; box-shadow: 0 8px 16px rgba(0,0,0,0.3); animation: pulse 2s infinite;">
            <h1 style="margin: 0; font-size: 36px; text-shadow: 2px 2px 4px rgba(0,0,0,0.4);">🏆 游戏结算 / GAME SETTLED 🏆</h1>
            <p style="margin: 15px 0 0 0; font-size: 28px; font-weight: bold; text-shadow: 1px 1px 3px rgba(0,0,0,0.4);">
                恭喜 <span style="color: #ffeaa7; text-decoration: underline;">{winner_text}</span> 以 <span style="color: #55efc4;">{winner_score} 分</span> 获得最终胜利！
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

st.markdown("---")

# ============================================================
# Split Screen Layout
# ============================================================
col_p1, col_p2 = st.columns(2)


def render_player_column(target_is_p1):
    p_name = "Player 1" if target_is_p1 else "Player 2"
    is_mine = target_is_p1 == my_player_is_p1
    turn_is_this_player = (state["turn"] == p_name) and not state["game_over"]
    score = state["p1_score"] if target_is_p1 else state["p2_score"]
    staging = state["p1_staging"] if target_is_p1 else state["p2_staging"]
    scoring = state["p1_scoring"] if target_is_p1 else state["p2_scoring"]
    hand = state["p1_hand"] if target_is_p1 else state["p2_hand"]

    with st.container():
        label = "🔵 Player 1 Zone" if target_is_p1 else "🔴 Player 2 Zone"
        if is_mine:
            label += " (You)"
        st.markdown(f"### {label}")

        if turn_is_this_player:
            if is_mine:
                st.success(f"⚡ Your turn (Remaining AP: {state['ap']})")
            else:
                st.info("⏳ Opponent's turn, please wait...")
        else:
            st.caption(f"(Current Score: {score})")

        if is_mine and can_act:
            b1, b2, b3 = st.columns(3)
            with b1:
                if st.button("🎴 Draw Card (-1 AP)", key=f"draw_{p_name}"):
                    if state["ap"] > 0 and len(state["deck"]) > 0:
                        card = state["deck"].pop(0)
                        state["ap"] -= 1
                        if card[1] in ["B", "R"]:
                            staging.append(card)
                            add_log(state, f"{p_name} drew number card [{card[0]}-{card[1]}], entered staging area.")
                            check_auto_same_color_match(state, target_is_p1)
                        elif card[0] == "JOKER":
                            st.warning(f"🃏 {p_name} drew a JOKER card! Chaos effect triggered!")
                            auto_joker_transfer(state, target_is_p1)
                        else:
                            hand.append(card)
                            add_log(state, f"{p_name} drew tactical card [{card[0]}].")
                        
                        check_game_over_and_settle(state)
                        save_game(room_code, state)
                        st.rerun()
                    else:
                        st.warning("Insufficient AP or empty deck!")
            with b2:
                if st.button("🌿 Neutralize (0 pts)", key=f"neutral_{p_name}"):
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
                                add_log(state, f"🌿 {p_name} manually neutralized mixed pair (No.{v}): 0 pts.")
                                matched = True
                                break
                        if matched:
                            save_game(room_code, state)
                            st.rerun()
                        else:
                            st.warning("No opposite-color cards available for pairing!")
                    else:
                        st.warning("Staging area has fewer than 2 cards!")
            with b3:
                if st.button("⏭️ End Turn", key=f"end_{p_name}"):
                    state["ap"] = 2
                    state["turn"] = "Player 2" if target_is_p1 else "Player 1"
                    state["active_tactical"] = None
                    state["tactical_player"] = None
                    state["q_selected_own_card"] = None
                    add_log(state, f"Turn passed: Current turn is {state['turn']}.")
                    save_game(room_code, state)
                    st.rerun()

        st.markdown("---")

        # --- 1. Hand Cards ---
        st.markdown(f"**🎒 {p_name}'s Hand Cards**")
        if hand:
            h_cols = st.columns(len(hand) if len(hand) <= 4 else 4)
            for h_idx, hcard in enumerate(hand):
                with h_cols[h_idx % 4]:
                    st.markdown(
                        render_card_html(hcard[0], hcard[0], size="large"),
                        unsafe_allow_html=True,
                    )
                    if is_mine and can_act:
                        if st.button(f"Play #{h_idx+1}", key=f"play_{p_name}_{h_idx}"):
                            ctype = hcard[0]
                            if ctype == "J":
                                hand.pop(h_idx)
                                state["ap"] += 1
                                add_log(state, f"⚡ {p_name} played J card: +1 AP!")
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
                                    add_log(state, f"🔄 {p_name} played A card: swapped both staging areas!")
                                    check_auto_same_color_match(state, True)
                                    check_auto_same_color_match(state, False)
                                    check_game_over_and_settle(state)
                                    save_game(room_code, state)
                                    st.rerun()
                                else:
                                    st.warning("⚠️ Insufficient AP!")
                            elif ctype == "Q":
                                if state["ap"] > 0:
                                    state["active_tactical"] = "Q"
                                    state["tactical_hand_idx"] = h_idx
                                    state["tactical_player"] = target_is_p1
                                    state["q_selected_own_card"] = None
                                    add_log(state, f"🎯 {p_name} preparing Q card: select own card.")
                                    save_game(room_code, state)
                                    st.rerun()
                                else:
                                    st.warning("⚠️ Insufficient AP!")
                            elif ctype == "K":
                                if state["ap"] > 0:
                                    state["active_tactical"] = "K"
                                    state["tactical_hand_idx"] = h_idx
                                    state["tactical_player"] = target_is_p1
                                    add_log(state, f"🎯 {p_name} preparing K card: select card to push.")
                                    save_game(room_code, state)
                                    st.rerun()
                                else:
                                    st.warning("⚠️ Insufficient AP!")
        else:
            st.caption("Hand library is empty")

        st.markdown("---")

        # --- 2. Staging Area ---
        st.markdown(f"**📥 {p_name}'s Staging Area**")
        if (
            state["active_tactical"] == "K"
            and can_act
            and target_is_p1 == state["tactical_player"]
        ):
            st.info("👉 [K Card Active] Click the card to push to opponent:")
        elif state["active_tactical"] == "Q" and can_act:
            if state["q_selected_own_card"] is None:
                if target_is_p1 == state["tactical_player"]:
                    st.info("👉 [Q Card Active] Select a card from your staging area:")
            else:
                if target_is_p1 != state["tactical_player"]:
                    st.info("👉 [Q Card Active] Click a card in opponent's staging area:")

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
                        if st.button(f"Push #{idx+1}", key=f"push_k_{target_is_p1}_{idx}"):
                            h_idx = state["tactical_hand_idx"]
                            (state["p1_hand"] if target_is_p1 else state["p2_hand"]).pop(h_idx)
                            state["ap"] -= 1
                            pushed_card = staging.pop(idx)
                            if target_is_p1:
                                state["p2_staging"].append(pushed_card)
                                add_log(state, f"🎯 Player 1 pushed {pushed_card} to Player 2!")
                                check_auto_same_color_match(state, False)
                            else:
                                state["p1_staging"].append(pushed_card)
                                add_log(state, f"🎯 Player 2 pushed {pushed_card} to Player 1!")
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
                            if st.button(f"Select #{idx+1}", key=f"q_own_{target_is_p1}_{idx}"):
                                state["q_selected_own_card"] = [target_is_p1, idx, card]
                                add_log(state, f"🔄 {p_name} locked card {card}, click opponent's card to swap.")
                                save_game(room_code, state)
                                st.rerun()

                    elif (
                        state["active_tactical"] == "Q"
                        and can_act
                        and state["q_selected_own_card"] is not None
                    ):
                        if target_is_p1 != state["tactical_player"]:
                            if st.button(f"Swap #{idx+1}", key=f"q_target_{target_is_p1}_{idx}"):
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
                                    add_log(state, f"🔄 Player 1 swapped {own_card} with Player 2's {target_card}!")
                                else:
                                    state["p2_staging"][own_idx] = target_card
                                    state["p1_staging"][idx] = own_card
                                    add_log(state, f"🔄 Player 2 swapped {own_card} with Player 1's {target_card}!")

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
            st.caption("Staging area is empty")

        st.markdown("---")

        # --- 3. Scored Area ---
        st.markdown(f"**🏆 {p_name} Scored Area (Total Score: {score})**")
        if scoring:
            for idx, s_item in enumerate(scoring):
                st.markdown(
                    f"<span style='font-size:14px;'>Pair #{idx+1}</span>",
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
            st.caption("No pairs in scored area yet")


with col_p1:
    render_player_column(True)

with col_p2:
    render_player_column(False)

st.markdown("---")
st.subheader("📋 Game Dynamic Logs")
log_container = st.container(height=180)
with log_container:
    for lg in state["logs"]:
        st.markdown(f"- {lg}")
