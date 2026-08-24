import { NavLink } from 'react-router-dom'
import '../css/Navbar.css'

function NavBar() {
  const linkClass = ({ isActive }) =>
    `navbar-link${isActive ? ' active' : ''}`

  return (
    <nav className="navbar glass">
      <div className="app-name">
        <NavLink to="/" end>Velo</NavLink>
      </div>
      <div className="right">
        <NavLink to="/" end className={linkClass}>Home</NavLink>
        <NavLink to="/about" className={linkClass}>About</NavLink>
      </div>
    </nav>
  )
}

export default NavBar
