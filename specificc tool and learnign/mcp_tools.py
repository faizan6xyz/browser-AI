allowed = {
    # --- core (always enabled) ---
    "browser_click", "browser_close", "browser_console_messages",
    "browser_drag", "browser_evaluate", "browser_file_upload",
    "browser_fill_form", "browser_handle_dialog", "browser_hover",
    "browser_navigate", "browser_navigate_back", "browser_network_requests",
    "browser_press_key", "browser_resize", "browser_run_code",
    "browser_select_option", "browser_snapshot", "browser_take_screenshot",
    "browser_type", "browser_wait_for",
    "browser_tabs",  # tab management

    # --- config (--caps=config) ---
    "browser_get_config",

    # --- network (--caps=network) ---
    "browser_network_state_set", "browser_route",
    "browser_route_list", "browser_unroute",

    # --- storage (--caps=storage) ---
    "browser_cookie_clear", "browser_cookie_delete", "browser_cookie_get",
    "browser_cookie_list", "browser_cookie_set",
    "browser_localstorage_clear", "browser_localstorage_delete",
    "browser_localstorage_get", "browser_localstorage_list",
    "browser_localstorage_set",
    "browser_sessionstorage_clear", "browser_sessionstorage_delete",
    "browser_sessionstorage_get", "browser_sessionstorage_list",
    "browser_sessionstorage_set",
    "browser_set_storage_state", "browser_storage_state",

    # --- devtools (--caps=devtools) ---
    "browser_hide_highlight", "browser_highlight", "browser_pick_locator",
    "browser_resume", "browser_start_tracing", "browser_start_video",
    "browser_stop_tracing", "browser_stop_video", "browser_video_chapter",

    # --- vision, coordinate-based (--caps=vision) ---
    "browser_mouse_click_xy", "browser_mouse_down", "browser_mouse_drag_xy",
    "browser_mouse_move_xy", "browser_mouse_up", "browser_mouse_wheel",

    # --- pdf (--caps=pdf) ---
    "browser_pdf_save",

    # --- testing assertions (--caps=testing) ---
    "browser_generate_locator", "browser_verify_element_visible",
    "browser_verify_list_visible", "browser_verify_text_visible",
    "browser_verify_value",
}