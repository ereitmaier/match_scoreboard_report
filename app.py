import streamlit as st
import requests
import yaml
import pandas as pd
import re

# Optionele import van WeasyPrint voor PDF-generatie
try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except Exception:
    WEASYPRINT_AVAILABLE = False

APP_VERSION = "v2.1.4 - PDF Icons & Styling Fix"

st.set_page_config(
    page_title=f"Matchcenter & Report ({APP_VERSION})",
    page_icon="⚽",
    layout="wide"
)

# -----------------------------------------------------------------------------
# CSS Styling
# -----------------------------------------------------------------------------
st.markdown("""
    <style>
    .score-banner {
        background-color: #2d2d3f;
        padding: 20px;
        border-radius: 12px;
        text-align: center;
        margin-bottom: 25px;
    }
    .score-title {
        font-size: 32px;
        font-weight: bold;
        color: #ffffff;
        margin: 0;
    }
    .score-sub {
        font-size: 14px;
        color: #aaaaaa;
        margin-top: 5px;
    }
    </style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Helper Functies voor Rapportage & Statistieken
# -----------------------------------------------------------------------------
def clean_player_name(raw_name):
    """Verwijdert rugnummers, haakjes en extra spaties uit de spelersnaam."""
    if not raw_name:
        return ""
    s = str(raw_name)
    s = re.sub(r'\(.*?\)', '', s)
    s = re.sub(r'^\d+[\.\s\-]+', '', s)
    return s.strip()

def parse_time_to_minutes(time_str, half_duration=45):
    try:
        s = str(time_str).strip().upper()
        if "RUST" in s or "PAUZE" in s:
            return float(half_duration)
        if "PRE_VERLENGING" in s:
            return float(half_duration * 2)
        if "HALVERWEGE_VERL" in s:
            return float((half_duration * 2) + 15)

        period_offset = 0.0
        if "P4" in s:
            period_offset = float((half_duration * 2) + 15)
            s = s.replace("P4", "").replace("|", "").strip()
        elif "P3" in s:
            period_offset = float(half_duration * 2)
            s = s.replace("P3", "").replace("|", "").strip()
        elif "P2" in s:
            period_offset = float(half_duration)
            s = s.replace("P2", "").replace("|", "").strip()
        elif "P1" in s:
            s = s.replace("P1", "").replace("|", "").strip()

        if "+" in s:
            s = s.split("+")[0]

        if ":" in s:
            parts = s.split(":")
            mins = float(parts[0]) + float(parts[1]) / 60.0
        else:
            mins = float(s)

        return period_offset + mins
    except Exception:
        return 0.0

def calculate_goalscorers(events_info, home_team, away_team):
    scorers = {}
    for ev in events_info:
        if ev.get('marker'):
            continue
        ev_name = str(ev.get('event', ''))
        ev_icon = str(ev.get('icon', ''))
        extra = str(ev.get('extra', ''))
        own_goal = ev.get('own_goal', False)
        t_str = str(ev.get('time', '')).strip()

        is_goal = False
        if "Doelpunt" in ev_name or "Goal" in ev_name or "⚽" in ev_icon:
            is_goal = True
        elif "Penalty" in ev_name:
            if not any(x in extra for x in ["Naast/Over", "Gestopt", "Off target", "Blocked"]):
                is_goal = True

        if is_goal:
            raw_player = str(ev.get('player', 'Onbekend')).strip()
            p_name = clean_player_name(raw_player)
            team_key = ev.get('team', '')

            if own_goal:
                scoring_team = away_team if team_key == 'home' else home_team
                display_name = f"{p_name} (Eigen Doelpunt)"
            else:
                scoring_team = home_team if team_key == 'home' else away_team
                display_name = p_name

            clean_time = t_str.replace("P1 |", "").replace("P2 |", "").replace("P3 |", "").replace("P4 |", "").strip()
            if ":" in clean_time:
                clean_time = clean_time.split(":")[0]
            if clean_time and not clean_time.endswith("'"):
                clean_time = f"{clean_time}'"

            key = f"{scoring_team}_{display_name}"
            if key not in scorers:
                scorers[key] = {'name': display_name, 'team': scoring_team, 'goals': 0, 'minutes': []}
            scorers[key]['goals'] += 1
            if clean_time:
                scorers[key]['minutes'].append(clean_time)

    result = list(scorers.values())
    result.sort(key=lambda x: x['goals'], reverse=True)
    return result

def calculate_cards(events_info, home_team, away_team):
    cards = {}
    for ev in events_info:
        if ev.get('marker'):
            continue
        ev_name = str(ev.get('event', ''))
        ev_icon = str(ev.get('icon', ''))
        t_str = str(ev.get('time', ''))
        team_key = ev.get('team', '')
        t_label = home_team if team_key == 'home' else (away_team if team_key == 'away' else '-')

        card_type = None
        if "Gele kaart" in ev_name or "🟨" in ev_icon or "Geel" in ev_name:
            card_type = "🟨 Geel"
        elif "Rode kaart" in ev_name or "🟥" in ev_icon or "Rood" in ev_name:
            card_type = "🟥 Rood"

        if card_type:
            raw_player = str(ev.get('player', 'Onbekend')).strip()
            p_name = clean_player_name(raw_player)
            key = f"{t_label}_{p_name}"

            if key not in cards:
                cards[key] = {'name': p_name, 'team': t_label, 'yellow': 0, 'red': 0, 'times': []}

            if "Geel" in card_type:
                cards[key]['yellow'] += 1
            elif "Rood" in card_type:
                cards[key]['red'] += 1

            cards[key]['times'].append(f"{t_str} ({card_type})")

    return list(cards.values())

def calculate_player_minutes(starters_h, subs_h, starters_a, subs_a, events_info, total_match_minutes, half_duration):
    players = {}
    def add_player(p, team_key, is_starter):
        raw_name = str(p.get('name', '')).strip() if isinstance(p, dict) else str(p).strip()
        c_name = clean_player_name(raw_name)
        if not c_name:
            return
        num = p.get('number', '') if isinstance(p, dict) else ''
        key = f"{team_key}_{c_name.lower()}"
        players[key] = {
            'clean_name': c_name, 'number': num, 'team': team_key,
            'on_field': is_starter, 'last_in': 0.0 if is_starter else None, 'total_minutes': 0.0
        }

    for p in (starters_h or []): add_player(p, 'home', True)
    for p in (subs_h or []): add_player(p, 'home', False)
    for p in (starters_a or []): add_player(p, 'away', True)
    for p in (subs_a or []): add_player(p, 'away', False)

    def find_player_key(team_key, search_text):
        s_clean = clean_player_name(search_text).lower()
        if not s_clean: return None
        exact_key = f"{team_key}_{s_clean}"
        if exact_key in players: return exact_key
        for k, pdata in players.items():
            if pdata['team'] == team_key:
                p_clean = pdata['clean_name'].lower()
                if s_clean in p_clean or p_clean in s_clean: return k
        return None

    for ev in events_info:
        if ev.get('marker'): continue
        ev_name = str(ev.get('event', ''))
        ev_icon = str(ev.get('icon', ''))
        
        if "Wissel" in ev_name or "🔄" in ev_icon:
            t_min = parse_time_to_minutes(ev.get('time', 0), half_duration)
            team = ev.get('team', '')
            p_out_name, p_in_name = None, None
            extra_val = str(ev.get('extra', ''))
            player_val = str(ev.get('player', ''))

            if "In:" in extra_val and "Out:" in extra_val:
                m_in = re.search(r'In:\s*([^\|]+)', extra_val)
                m_out = re.search(r'Out:\s*([^\|]+)', extra_val)
                if m_in: p_in_name = m_in.group(1).strip()
                if m_out: p_out_name = m_out.group(1).strip()
            elif "->" in player_val:
                parts = player_val.split("->")
                p_out_name = parts[0].strip()
                p_in_name = parts[1].strip()

            if p_out_name:
                key_out = find_player_key(team, p_out_name)
                if key_out and players[key_out]['on_field']:
                    players[key_out]['total_minutes'] += (t_min - players[key_out]['last_in'])
                    players[key_out]['on_field'] = False

            if p_in_name:
                key_in = find_player_key(team, p_in_name)
                if key_in:
                    players[key_in]['on_field'] = True
                    players[key_in]['last_in'] = t_min

    for key, pdata in players.items():
        if pdata['on_field'] and pdata['last_in'] is not None:
            players[key]['total_minutes'] += (total_match_minutes - pdata['last_in'])
        players[key]['total_minutes'] = round(players[key]['total_minutes'])

    result = list(players.values())
    result.sort(key=lambda x: x['total_minutes'], reverse=True)
    return result

def extract_roster(team_data):
    starters, substitutes = [], []
    if isinstance(team_data, dict):
        starters = team_data.get("starters", [])
        substitutes = team_data.get("substitutes", [])
    elif isinstance(team_data, list):
        starters = team_data
    return starters, substitutes

def get_players_from_events(events_info, team_key):
    """Fallback: haalt spelersnamen op uit de geregistreerde live events."""
    found_players = set()
    for ev in events_info:
        if ev.get("marker"):
            continue
        if ev.get("team") == team_key and ev.get("player"):
            p_name = clean_player_name(ev.get("player"))
            if p_name:
                found_players.add(p_name)
        extra = str(ev.get("extra", ""))
        if "In:" in extra and "Out:" in extra:
            m_in = re.search(r'In:\s*([^\|]+)', extra)
            m_out = re.search(r'Out:\s*([^\|]+)', extra)
            if ev.get("team") == team_key:
                if m_in: found_players.add(clean_player_name(m_in.group(1)))
                if m_out: found_players.add(clean_player_name(m_out.group(1)))
    return sorted(list(found_players))

def get_event_icon(ev_name, ev_icon):
    if ev_icon and ev_icon.strip():
        return ev_icon.strip()
    
    name_lower = str(ev_name).lower()
    if "doelpunt" in name_lower or "goal" in name_lower:
        return "⚽"
    elif "penalty" in name_lower:
        return "🎯"
    elif "geel" in name_lower or "gele kaart" in name_lower:
        return "🟨"
    elif "rood" in name_lower or "rode kaart" in name_lower:
        return "🟥"
    elif "wissel" in name_lower or "subst" in name_lower:
        return "🔄"
    return "📌"

def generate_pdf_report(match_info, home_score, away_score, starters_h, subs_h, starters_a, subs_a, events_info, minutes_list, goalscorers_list, cards_list, simple_mode=False):
    home_team = match_info.get("home", "Thuisploeg")
    away_team = match_info.get("away", "Uitploeg")
    match_date = match_info.get("date", "Onbekend")
    category = match_info.get("category", "B")
    fmt_val = match_info.get("format", 11)
    half_duration = match_info.get("half_duration", 45)

    # -------------------------------------------------------------------------
    # 1. HTML opbouwen voor Opstellingen
    # -------------------------------------------------------------------------
    def render_player_list_html(players, fallback_team_key):
        if players:
            items = []
            for p in players:
                if isinstance(p, dict):
                    num = f"#{p.get('number')} " if p.get('number') else ""
                    name = clean_player_name(p.get('name'))
                    items.append(f"{num}{name}")
                else:
                    items.append(clean_player_name(p))
            return "<br>".join(items)
        else:
            fallback_players = get_players_from_events(events_info, fallback_team_key)
            if fallback_players:
                return "<br>".join([f"• {p}" for p in fallback_players])
            return "<i>Geen spelers opgegeven</i>"

    home_starters_html = render_player_list_html(starters_h, "home")
    home_subs_html = render_player_list_html(subs_h, "home") if subs_h else "<i>Geen wisselspelers</i>"

    away_starters_html = render_player_list_html(starters_a, "away")
    away_subs_html = render_player_list_html(subs_a, "away") if subs_a else "<i>Geen wisselspelers</i>"

    # -------------------------------------------------------------------------
    # 2. HTML opbouwen voor Wedstrijdverloop
    # -------------------------------------------------------------------------
    events_html = ""
    for ev in events_info:
        t_str = ev.get("time", "")
        if ev.get("marker"):
            events_html += f"<tr class='marker-row'><td colspan='4'><b>⏱️ {ev.get('event', '')}</b> ({ev.get('extra', '')})</td></tr>"
        else:
            team_name = home_team if ev.get("team") == "home" else (away_team if ev.get("team") == "away" else "-")
            og = " (Eigen Doelpunt)" if ev.get("own_goal") else ""
            ev_name = ev.get('event', '')
            icon = get_event_icon(ev_name, ev.get('icon', ''))
            extra_val = str(ev.get('extra', ''))
            player_val = str(ev.get('player', ''))

            details_html = f"{clean_player_name(player_val)} {f'({extra_val})' if extra_val else ''}"
            events_html += f"<tr><td><b>{t_str}</b></td><td>{icon} {ev_name}{og}</td><td>{team_name}</td><td>{details_html}</td></tr>"

    # -------------------------------------------------------------------------
    # 3. HTML opbouwen voor Statistieken (Doelpuntenmakers & Kaarten)
    # -------------------------------------------------------------------------
    goalscorers_html = ""
    if goalscorers_list:
        for g in goalscorers_list:
            mins = f" ({', '.join(g['minutes'])})" if g['minutes'] else ""
            goalscorers_html += f"<tr><td>{g['name']}</td><td>{g['team']}</td><td>{g['goals']} ⚽{mins}</td></tr>"
    else:
        goalscorers_html = "<tr><td colspan='3'><i>Geen doelpunten geregistreerd</i></td></tr>"

    cards_html = ""
    if cards_list:
        for c in cards_list:
            times = ", ".join(c['times'])
            cards_html += f"<tr><td>{c['name']}</td><td>{c['team']}</td><td>{c['yellow']} 🟨 / {c['red']} 🟥</td><td>{times}</td></tr>"
    else:
        cards_html = "<tr><td colspan='4'><i>Geen kaarten geregistreerd</i></td></tr>"

    # -------------------------------------------------------------------------
    # 4. HTML opbouwen voor Gespeelde Minuten
    # -------------------------------------------------------------------------
    minutes_html = ""
    if not simple_mode and minutes_list:
        rows = ""
        for p in minutes_list:
            team_label = home_team if p['team'] == 'home' else away_team
            num_label = f"#{p['number']}" if p.get('number') else "-"
            rows += f"<tr><td>{num_label}</td><td>{p['clean_name']}</td><td>{team_label}</td><td><b>{int(p['total_minutes'])} min</b></td></tr>"
        
        minutes_html = f"""
        <div class="section-title">⏱️ Gespeelde Minuten per Speler</div>
        <table class="data-table">
            <thead>
                <tr><th>#</th><th>Speler</th><th>Team</th><th>Gespeelde Minuten</th></tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
        """

    # -------------------------------------------------------------------------
    # 5. Volledige HTML Template met emoji font-fallback support
    # -------------------------------------------------------------------------
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            @page {{ size: A4; margin: 15mm; }}
            body {{ font-family: 'Apple Color Emoji', 'Segoe UI Emoji', 'Noto Color Emoji', 'DejaVu Sans', 'Helvetica', 'Arial', sans-serif; color: #333; margin: 0; padding: 0; }}
            .header {{ text-align: center; background-color: #1e1e2e; color: #fff; padding: 15px; border-radius: 8px; }}
            .score {{ font-size: 26px; font-weight: bold; margin: 5px 0; }}
            .sub-info {{ font-size: 12px; color: #ccc; }}
            .section-title {{ font-size: 16px; font-weight: bold; border-bottom: 2px solid #2980b9; margin-top: 20px; padding-bottom: 5px; color: #2d2d3f; page-break-after: avoid; }}
            .page-break {{ page-break-before: always; }}
            .teams-table {{ width: 100%; margin-top: 10px; border-collapse: separate; border-spacing: 10px 0; }}
            .team-box {{ width: 50%; vertical-align: top; background: #f8f9fa; padding: 12px; border-radius: 6px; border: 1px solid #ddd; font-size: 12px; }}
            .team-box h3 {{ margin-top: 0; margin-bottom: 8px; color: #2980b9; font-size: 14px; }}
            table.data-table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 11px; }}
            table.data-table th, table.data-table td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: left; }}
            table.data-table th {{ background-color: #2d2d3f; color: white; }}
            .marker-row {{ background-color: #eaeded; text-align: center; }}
            .stats-container {{ width: 100%; border-collapse: separate; border-spacing: 10px 0; margin-top: 10px; }}
            .stats-box {{ vertical-align: top; width: 50%; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="score">{home_team} {home_score} - {away_score} {away_team}</div>
            <div class="sub-info">Datum: {match_date} | Categorie {category} | Wedstrijdvorm: {fmt_val}v{fmt_val} | Speeltijd: 2x {half_duration} min</div>
        </div>

        <!-- Pagina 1: Opstellingen -->
        <div class="section-title">👥 Opstellingen</div>
        <table class="teams-table">
            <tr>
                <td class="team-box">
                    <h3>🏠 {home_team}</h3>
                    <b>📋 Basis / Geregistreerd:</b><br>{home_starters_html}<br><br>
                    <b>🔄 Wissels:</b><br>{home_subs_html}
                </td>
                <td class="team-box">
                    <h3>🚩 {away_team}</h3>
                    <b>📋 Basis / Geregistreerd:</b><br>{away_starters_html}<br><br>
                    <b>🔄 Wissels:</b><br>{away_subs_html}
                </td>
            </tr>
        </table>

        <!-- Pagina 2: Wedstrijdverloop -->
        <div class="page-break"></div>
        <div class="section-title">📋 Wedstrijdverloop</div>
        <table class="data-table">
            <thead>
                <tr><th>Tijd</th><th>Gebeurtenis</th><th>Team</th><th>Speler / Details</th></tr>
            </thead>
            <tbody>
                {events_html}
            </tbody>
        </table>

        <!-- Pagina 3: Statistieken & Gespeelde Minuten -->
        <div class="page-break"></div>
        <div class="section-title">📊 Statistieken & Overzicht</div>
        <table class="stats-container">
            <tr>
                <td class="stats-box">
                    <b style="font-size: 13px;">⚽ Doelpuntenmakers</b>
                    <table class="data-table">
                        <thead>
                            <tr><th>Speler</th><th>Team</th><th>Goals</th></tr>
                        </thead>
                        <tbody>
                            {goalscorers_html}
                        </tbody>
                    </table>
                </td>
                <td class="stats-box">
                    <b style="font-size: 13px;">🟨 / 🟥 Kaarten</b>
                    <table class="data-table">
                        <thead>
                            <tr><th>Speler</th><th>Team</th><th>Kaarten</th><th>Details</th></tr>
                        </thead>
                        <tbody>
                            {cards_html}
                        </tbody>
                    </table>
                </td>
            </tr>
        </table>

        {minutes_html}
    </body>
    </html>
    """

    if WEASYPRINT_AVAILABLE:
        return HTML(string=html_content).write_pdf()
    else:
        return html_content.encode('utf-8')
    
# -----------------------------------------------------------------------------
# Weergave 1: Live Scoreboard Component (met Auto FT Detectie)
# -----------------------------------------------------------------------------
@st.fragment(run_every="5s")
def render_live_scoreboard(match_key):
    url = f"https://team-level-up.com/match-reporter/live_{match_key}.json"
    
    try:
        response = requests.get(url, timeout=3)
        if response.status_code != 200:
            st.info(f"Wachten op gegevens voor live wedstrijd '{match_key}'...")
            return
        data = response.json()
    except Exception:
        st.info("Wachten op de aftrap...")
        return

    period = str(data.get('period', 1))
    status = str(data.get('status', '')).upper()
    events = data.get("events", [])
    
    has_end_marker = any(
        ev.get("marker") and str(ev.get("event")).strip() in ["Einde wedstrijd", "End of Match", "Einde reguliere speeltijd"]
        for ev in events
    )

    is_finished = (
        period in ["FT", "Eindsignaal", "Afgelopen"] 
        or status in ["FT", "FINISHED", "ENDED"]
        or has_end_marker
    )

    if is_finished:
        st.session_state['match_finished'] = True
        st.rerun(scope="app")

    st.markdown(f"<p style='text-align: right; color: #666; font-size: 11px;'>Versie: {APP_VERSION}</p>", unsafe_allow_html=True)
    st.markdown(f"<h4 style='text-align: center; color: #aaa;'>{data.get('date', '')} — Periode: {period}</h4>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([2, 1.5, 2])
    c1.markdown(f"<h2 style='text-align: right;'>{data.get('home')}</h2>", unsafe_allow_html=True)
    c2.markdown(f"<h1 style='text-align: center; color: #27ae60;'>{data.get('scoreHome', 0)} - {data.get('scoreAway', 0)}</h1>", unsafe_allow_html=True)
    c3.markdown(f"<h2 style='text-align: left;'>{data.get('away')}</h2>", unsafe_allow_html=True)

    st.divider()
    st.subheader("⏱️ Live Wedstrijdverloop")
    
    if not events:
        st.write("Nog geen gebeurtenissen.")
        return

    for ev in reversed(events):
        if ev.get("marker"):
            st.caption(f"⏱️ **{ev.get('time')}** — *{ev.get('event')}*")
            continue

        minuut = f"**{ev.get('time')}**"
        speler = ev.get('player', '')
        team_naam = data.get('home') if ev.get('team') == 'home' else data.get('away')
        actie = ev.get('event')
        extra = ev.get('extra', '')
        icon = get_event_icon(actie, ev.get('icon', ''))

        if actie in ["Doelpunt", "Goal"]:
            st.success(f"⚽ {minuut} **GOAL {team_naam}!** — {speler} " + (f"*(Assist: {extra})*" if extra else ""))
        elif "kaart" in actie.lower() or "card" in actie.lower():
            st.warning(f"{icon} {minuut} **{actie} ({team_naam})** — {speler} " + (f"*({extra})*" if extra else ""))
        elif "wissel" in actie.lower() or "subst" in actie.lower():
            st.info(f"🔄 {minuut} **Wissel ({team_naam})** — {extra}")
        else:
            st.write(f"{icon} {minuut} {actie} ({team_naam}) — {speler} {extra}")

# -----------------------------------------------------------------------------
# Weergave 2: Volledig Rapport (Afgelopen Wedstrijd)
# -----------------------------------------------------------------------------
def render_full_report(data):
    st.success("🏁 De wedstrijd is afgelopen! Het officiële wedstrijdrapport is hieronder beschikbaar.")
    
    match_info = data.get("match", {})
    teams_info = data.get("teams", {})
    events_info = data.get("events", [])

    simple_mode = match_info.get("simple_mode", data.get("simple_mode", False))
    
    home_team = match_info.get("home") or data.get("home") or "Thuisploeg"
    away_team = match_info.get("away") or data.get("away") or "Uitploeg"
    match_date = match_info.get("date") or data.get("date") or "Onbekend"
    
    category = match_info.get("category", data.get("category", "B"))
    fmt_val = match_info.get("format", data.get("format", 11))
    half_duration = match_info.get("half_duration", data.get("half_duration", 45))
    
    has_extra_time = match_info.get("extra_time", data.get("extra_time", False))
    total_match_minutes = (half_duration * 2) + (30 if has_extra_time else 0)

    home_data = teams_info.get("home", {}) if isinstance(teams_info, dict) else data.get("home", [])
    starters_h, subs_h = extract_roster(home_data)

    away_data = teams_info.get("away", {}) if isinstance(teams_info, dict) else data.get("away", [])
    starters_a, subs_a = extract_roster(away_data)

    match_info["home"] = home_team
    match_info["away"] = away_team
    match_info["date"] = match_date

    home_score = 0
    away_score = 0
    for ev in events_info:
        name = ev.get("event", "")
        team = ev.get("team", "")
        own_goal = ev.get("own_goal", False)
        extra = ev.get("extra", "")

        is_goal = False
        if name in ["Doelpunt", "Goal"]:
            is_goal = True
        elif name == "Penalty":
            if not any(x in str(extra) for x in ["Naast/Over", "Gestopt", "Off target", "Blocked"]):
                is_goal = True

        if is_goal:
            if own_goal:
                if team == "home": away_score += 1
                elif team == "away": home_score += 1
            else:
                if team == "home": home_score += 1
                elif team == "away": away_score += 1

    minutes_list = calculate_player_minutes(starters_h, subs_h, starters_a, subs_a, events_info, total_match_minutes, half_duration)
    goalscorers_list = calculate_goalscorers(events_info, home_team, away_team)
    cards_list = calculate_cards(events_info, home_team, away_team)

    st.markdown(f"""
        <div class="score-banner">
            <div class="score-title">{home_team} &nbsp; {home_score} - {away_score} &nbsp; {away_team}</div>
            <div class="score-sub">Datum: {match_date} &nbsp;|&nbsp; Categorie {category} &nbsp;|&nbsp; Wedstrijdvorm: {fmt_val}v{fmt_val} &nbsp;|&nbsp; Speeltijd: 2x {half_duration} min</div>
        </div>
    """, unsafe_allow_html=True)

    pdf_file_data = generate_pdf_report(match_info, home_score, away_score, starters_h, subs_h, starters_a, subs_a, events_info, minutes_list, goalscorers_list, cards_list, simple_mode=simple_mode)
    file_ext = "pdf" if WEASYPRINT_AVAILABLE else "html"
    mime_type = "application/pdf" if WEASYPRINT_AVAILABLE else "text/html"

    st.sidebar.download_button(
        label=f"📄 Download Wedstrijdrapport ({file_ext.upper()})",
        data=pdf_file_data,
        file_name=f"rapport_{match_date}_{home_team}_vs_{away_team}.{file_ext}",
        mime=mime_type,
        use_container_width=True
    )

    tab_log, tab_lineup, tab_stats, tab_raw = st.tabs(["📋 Live Wedstrijdverloop", "👥 Opstellingen", "📊 Statistieken", "📄 Ruwe Data & Export"])

    with tab_log:
        st.subheader("Wedstrijdverloop & Gebeurtenissen")
        if events_info:
            log_data = []
            for ev in events_info:
                icon = get_event_icon(ev.get('event', ''), ev.get('icon', ''))
                if ev.get("marker"):
                    log_data.append({
                        "Tijd": ev.get("time", ""),
                        "Gebeurtenis": f"⏱️ {ev.get('event', '')}",
                        "Team": "-",
                        "Speler": "-",
                        "Details": ev.get("extra", "")
                    })
                else:
                    t_label = home_team if ev.get("team") == "home" else (away_team if ev.get("team") == "away" else "")
                    og_label = " (Eigen Doelpunt)" if ev.get("own_goal") else ""
                    log_data.append({
                        "Tijd": ev.get("time", ""),
                        "Gebeurtenis": f"{icon} {ev.get('event', '')}{og_label}",
                        "Team": t_label,
                        "Speler": clean_player_name(ev.get("player", "-")),
                        "Details": ev.get("extra", "")
                    })
            st.dataframe(pd.DataFrame(log_data), use_container_width=True, hide_index=True)

    with tab_lineup:
        col_h, col_a = st.columns(2)
        with col_h:
            st.subheader(f"🏠 {home_team}")
            if starters_h or subs_h:
                st.markdown("**📋 Begin-opstelling:**")
                for p in starters_h: st.write(f"• #{p.get('number', '')} {clean_player_name(p.get('name', ''))}")
                if subs_h:
                    st.markdown("**🔄 Wissels:**")
                    for p in subs_h: st.write(f"• #{p.get('number', '')} {clean_player_name(p.get('name', ''))}")
            else:
                event_players_h = get_players_from_events(events_info, "home")
                if event_players_h:
                    st.markdown("**Geregistreerde Spelers (uit verloop):**")
                    for name in event_players_h: st.write(f"• {name}")
                else:
                    st.caption("Geen opstelling doorgegeven.")

        with col_a:
            st.subheader(f"🚩 {away_team}")
            if starters_a or subs_a:
                st.markdown("**📋 Begin-opstelling:**")
                for p in starters_a: st.write(f"• #{p.get('number', '')} {clean_player_name(p.get('name', ''))}")
                if subs_a:
                    st.markdown("**🔄 Wissels:**")
                    for p in subs_a: st.write(f"• #{p.get('number', '')} {clean_player_name(p.get('name', ''))}")
            else:
                event_players_a = get_players_from_events(events_info, "away")
                if event_players_a:
                    st.markdown("**Geregistreerde Spelers (uit verloop):**")
                    for name in event_players_a: st.write(f"• {name}")
                else:
                    st.caption("Geen opstelling doorgegeven.")

    with tab_stats:
        col_g, col_c = st.columns(2)
        with col_g:
            st.subheader("⚽ Doelpuntenmakers")
            if goalscorers_list:
                st.dataframe(pd.DataFrame([{
                    "Speler": g['name'], "Team": g['team'],
                    "Doelpunten": f"{g['goals']} ⚽ ({', '.join(g['minutes'])})" if g['minutes'] else f"{g['goals']} ⚽"
                } for g in goalscorers_list]), use_container_width=True, hide_index=True)
            else:
                st.info("Geen doelpunten geregistreerd.")
        with col_c:
            st.subheader("🟨 / 🟥 Kaarten & Sancties")
            if cards_list:
                st.dataframe(pd.DataFrame([{
                    "Speler": c['name'], "Team": c['team'], "Geel": c['yellow'], "Rood": c['red'], "Tijdstip(pen)": ", ".join(c['times'])
                } for c in cards_list]), use_container_width=True, hide_index=True)
            else:
                st.info("Geen kaarten geregistreerd.")

        if not simple_mode:
            st.divider()
            st.subheader("⏱️ Gespeelde Minuten per Speler")
            if minutes_list:
                st.dataframe(pd.DataFrame([{
                    "Rugnummer": p['number'], "Speler": p['clean_name'],
                    "Team": home_team if p['team'] == 'home' else away_team, "Gespeelde Minuten": f"{int(p['total_minutes'])} min"
                } for p in minutes_list]), use_container_width=True, hide_index=True)
            else:
                st.info("Geen minutendata beschikbaar.")

    with tab_raw:
        yaml_string = yaml.dump(data, default_flow_style=False, allow_unicode=True)
        st.download_button("💾 Download als YAML Bestand", data=yaml_string, file_name=f"export_match_{match_date}_{home_team}.yaml", mime="text/yaml")
        st.code(yaml_string, language="yaml")

# -----------------------------------------------------------------------------
# Sidebar Configuratie & Versie
# -----------------------------------------------------------------------------
st.sidebar.title("⚽ TLU Matchcenter")
st.sidebar.caption(f"🚀 **App Versie:** `{APP_VERSION}`")
st.sidebar.markdown("---")

# -----------------------------------------------------------------------------
# Hoofd Routing & Logica
# -----------------------------------------------------------------------------
query_params = st.query_params
match_id = query_params.get("match", None)
file_param = query_params.get("file", None)

if match_id:
    url = f"https://team-level-up.com/match-reporter/live_{match_id}.json"
    is_finished = st.session_state.get('match_finished', False)
    
    if not is_finished:
        try:
            res = requests.get(url, timeout=3)
            if res.status_code == 200:
                match_json = res.json()
                period = str(match_json.get('period', 1))
                status = str(match_json.get('status', '')).upper()
                events = match_json.get("events", [])
                
                has_end_marker = any(
                    ev.get("marker") and str(ev.get("event")).strip() in ["Einde wedstrijd", "End of Match", "Einde reguliere speeltijd"]
                    for ev in events
                )

                if period in ["FT", "Eindsignaal", "Afgelopen"] or status in ["FT", "FINISHED", "ENDED"] or has_end_marker:
                    is_finished = True
        except Exception:
            pass

    if is_finished:
        try:
            full_data = requests.get(url, timeout=5).json()
            render_full_report(full_data)
        except Exception as e:
            st.error(f"Fout bij het ophalen van het eindrapport: {e}")
    else:
        render_live_scoreboard(match_id)

elif file_param:
    target_url = f"https://team-level-up.com/match-reporter/matches/{file_param}"
    try:
        data = yaml.safe_load(requests.get(target_url, timeout=10).text)
        render_full_report(data)
    except Exception as e:
        st.error(f"Fout bij laden via URL: {e}")

else:
    st.info("👋 Geen wedstrijd geselecteerd. Gebruik een unieke match URL (`?match=jouw_hash`) of upload een YAML-bestand.")