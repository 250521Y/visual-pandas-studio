import {useEffect,Suspense,lazy} from 'react';
import {BrowserRouter,Routes,Route,useLocation,Navigate} from 'react-router-dom';
import {MotionConfig,motion} from 'motion/react';
import {Layout} from './components/Layout';
import {Loading,Toast} from './components/UI';
import {useStudio} from './store';
const Home=lazy(()=>import('./pages/Home')),Datasets=lazy(()=>import('./pages/Datasets')),Cleaning=lazy(()=>import('./pages/Cleaning')),Transform=lazy(()=>import('./pages/Transform')),Statistics=lazy(()=>import('./pages/Statistics')),Visualization=lazy(()=>import('./pages/Visualization')),Reports=lazy(()=>import('./pages/Reports'));
function Pages(){const location=useLocation();useEffect(()=>{window.scrollTo(0,0)},[location.pathname]);return <Suspense fallback={<Loading/>}><motion.div key={location.pathname} initial={{opacity:0}} animate={{opacity:1}} transition={{duration:.18}}><Routes><Route path="/" element={<Home/>}/><Route element={<Layout/>}><Route path="/datasets" element={<Datasets/>}/><Route path="/cleaning" element={<Cleaning/>}/><Route path="/transform" element={<Transform/>}/><Route path="/statistics" element={<Statistics/>}/><Route path="/visualization" element={<Visualization/>}/><Route path="/reports" element={<Reports/>}/></Route><Route path="*" element={<Navigate to="/" replace/>}/></Routes></motion.div></Suspense>}
export default function App(){const {init,ready}=useStudio();useEffect(()=>{init()},[init]);return <MotionConfig reducedMotion="user"><BrowserRouter>{ready?<Pages/>:<Loading/>}<Toast/></BrowserRouter></MotionConfig>}
