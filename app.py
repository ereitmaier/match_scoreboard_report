APP_VERSION = "v2.1.1 - Fix Team Names in Live Report"

# -----------------------------------------------------------------------------
# Weergave 2: Volledig Rapport (Afgelopen Wedstrijd)
# -----------------------------------------------------------------------------
def render_full_report(data):
    st.success("🏁 De wedstrijd is afgelopen! Het officiële wedstrijdrapport is hieronder beschikbaar.")
    
    # Check zowel het 'match' blok (YAML) als de losse root-velden (live JSON)
    match_info = data.get("match", {})
    teams_info = data.get("teams", {})
    events_info = data.get("events", [])

    simple_mode = match_info.get("simple_mode", data.get("simple_mode", False))
    
    # 🔧 FIX: Haal teamnamen en datum eerst op uit match_info, anders uit de root (live JSON)
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

    # Zorg dat de match_info dictionary ook de correcte teamnamen bevat voor de PDF generator
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
                        "Gebeurtenis": f"{ev.get('icon', '')} {ev.get('event', '')}{og_label}",
                        "Team": t_label,
                        "Speler": clean_player_name(ev.get("player", "-")),
                        "Details": ev.get("extra", "")
                    })
            st.dataframe(pd.DataFrame(log_data), use_container_width=True, hide_index=True)

    with tab_lineup:
        col_h, col_a = st.columns(2)
        with col_h:
            st.subheader(f"🏠 {home_team}")
            st.markdown("**Begin-opstelling:**")
            if starters_h:
                for p in starters_h: st.write(f"• #{p.get('number', '')} {clean_player_name(p.get('name', ''))}")
            else:
                st.caption("Geen opstelling doorgegeven.")
            if subs_h:
                st.markdown("**Wissels:**")
                for p in subs_h: st.write(f"• #{p.get('number', '')} {clean_player_name(p.get('name', ''))}")
        with col_a:
            st.subheader(f"🚩 {away_team}")
            st.markdown("**Begin-opstelling:**")
            if starters_a:
                for p in starters_a: st.write(f"• #{p.get('number', '')} {clean_player_name(p.get('name', ''))}")
            else:
                st.caption("Geen opstelling doorgegeven.")
            if subs_a:
                st.markdown("**Wissels:**")
                for p in subs_a: st.write(f"• #{p.get('number', '')} {clean_player_name(p.get('name', ''))}")

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