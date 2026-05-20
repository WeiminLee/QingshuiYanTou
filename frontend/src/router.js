import { createRouter, createWebHistory } from 'vue-router'
import Home from './views/Home.vue'
import ReportView from './views/ReportView.vue'
import StockDetail from './views/StockDetail.vue'
import TDesignDemo from './views/TDesignDemo.vue'
import TDesignChatSpike from './views/TDesignChatSpike.vue'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: Home,
  },
  {
    path: '/report',
    name: 'Report',
    component: ReportView,
  },
  {
    path: '/stock/:tsCode',
    name: 'StockDetail',
    component: StockDetail,
  },
  {
    path: '/tdesign-demo',
    name: 'TDesignDemo',
    component: TDesignDemo,
  },
  {
    path: '/spike-chat',
    name: 'TDesignChatSpike',
    component: TDesignChatSpike,
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
