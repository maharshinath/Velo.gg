import { Routes, Route } from 'react-router-dom'
import './css/App.css'
import NavBar from './components/Navbar'
import About from './pages/About'
import MakePrediction from './pages/MakePrediction'
import PredictionPage from './pages/PredictionPage'
import Compare from './pages/Compare'


function App() {


  return (
    <div className="app-shell">
      <NavBar />
      <main className="main-content">
          <Routes>
            <Route path='/' element={<MakePrediction />} />
            <Route path='/about' element={<About />} />
            <Route path='/predict/:team1/:team2' element={<PredictionPage />} />
            <Route path='/compare' element={<Compare />} />
          </Routes>
      </main>
    </div>
  )
}

export default App
