import { NavLink } from 'react-router-dom'
import '../css/Navbar.css'

const X_PROFILE = 'https://x.com/nonstop_natsu'

function NavBar() {
  const linkClass = ({ isActive }) =>
    `navbar-link${isActive ? ' active' : ''}`

  return (
    <nav className="navbar glass">
      <div className="navbar-left">
        <div className="app-name">
          <NavLink to="/" end>Velo.gg</NavLink>
        </div>
        <a
          className="navbar-signal"
          href={X_PROFILE}
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Natsu on X, @nonstop_natsu"
        >
          <span className="navbar-signal-label">BY</span>
          <svg className="navbar-signal-x" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path
              fill="currentColor"
              d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-4.714-6.231-5.401 6.231H2.74l7.727-8.836L1.254 2.25H8.08l4.253 5.622zm-1.161 17.52h1.833L7.084 4.126H5.117z"
            />
          </svg>
          <span className="navbar-signal-handle">@nonstop_natsu</span>
        </a>
      </div>
      <div className="right">
        <NavLink to="/" end className={linkClass}>Home</NavLink>
        <NavLink to="/about" className={linkClass}>About</NavLink>
      </div>
    </nav>
  )
}

export default NavBar
