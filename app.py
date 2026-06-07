import streamlit as st

from config import APP_NAME
from database import init_db
from seed_data import seed_demo_data
from views import admin_portal, employee_portal


def _current_portal() -> str:
    portal = st.query_params.get("portal", "employee")
    if isinstance(portal, list):
        portal = portal[0] if portal else "employee"
    return portal if portal in {"employee", "admin"} else "employee"


def _render_portal_nav(current: str) -> None:
    employee_class = "portal-nav-item active" if current == "employee" else "portal-nav-item"
    admin_class = "portal-nav-item active" if current == "admin" else "portal-nav-item"

    st.sidebar.markdown(
        f"""
        <style>
            section[data-testid="stSidebar"] .portal-nav {{
                display: flex;
                flex-direction: column;
                gap: 6px;
                width: 100%;
                margin: 8px 0 24px;
            }}
            section[data-testid="stSidebar"] .portal-nav-title {{
                margin: 4px 0 8px;
                color: #64748b;
                font-size: 0.78rem;
                font-weight: 700;
            }}
            section[data-testid="stSidebar"] .portal-nav-item {{
                display: flex;
                align-items: center;
                box-sizing: border-box;
                width: 100%;
                min-height: 38px;
                padding: 9px 12px;
                border-radius: 8px;
                color: #334155;
                text-decoration: none;
                font-size: 0.92rem;
                font-weight: 600;
                line-height: 1.25;
                background: transparent;
                border: 1px solid transparent;
            }}
            section[data-testid="stSidebar"] .portal-nav-item:hover {{
                background: #f1f5f9;
                color: #ff4b4b;
                text-decoration: none;
            }}
            section[data-testid="stSidebar"] .portal-nav-item.active {{
                background: #e5e7eb;
                color: #ff4b4b;
                font-weight: 700;
                border-color: #d1d5db;
            }}
            section[data-testid="stSidebar"] .admin-sidebar-spacer {{
                height: clamp(72px, calc(100vh - 520px), 420px);
            }}
        </style>
        <div class="portal-nav-title">入口</div>
        <div class="portal-nav">
            <a class="{employee_class}" href="?portal=employee" target="_self">员工端</a>
            <a class="{admin_class}" href="?portal=admin" target="_self">管理后台</a>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title=APP_NAME, layout="wide")
    init_db()
    seed_demo_data(force=False)

    st.title(APP_NAME)

    portal = _current_portal()
    _render_portal_nav(portal)

    if portal == "employee":
        employee_portal.render()
    else:
        admin_portal.render()


if __name__ == "__main__":
    main()
