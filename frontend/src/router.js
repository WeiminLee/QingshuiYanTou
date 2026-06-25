import { createRouter, createWebHistory } from 'vue-router'
import Home from './views/Home.vue'
import ReportView from './views/ReportView.vue'
import StockDetail from './views/StockDetail.vue'
import TDesignDemo from './views/TDesignDemo.vue'
import TDesignChatSpike from './views/TDesignChatSpike.vue'
import { whoami } from '@/api/account'

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
  { path: '/', redirect: '/portfolio' },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/select-identity',
    name: 'SelectIdentity',
    component: () => import('@/views/SelectIdentityView.vue'),
    meta: { requiresAuth: true, requiresUser: false },
  },
  {
    path: '/portfolio',
    name: 'Portfolio',
    component: () => import('@/views/PortfolioView.vue'),
    meta: { requiresAuth: true, requiresUser: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  if (to.meta.public) return true
  try {
    const me = await whoami()
    if (!me) return { path: '/login' }
    if (to.meta.requiresUser && !me.user) {
      return { path: '/select-identity' }
    }
    return true
  } catch (e) {
    if (e?.response?.status === 401) return { path: '/login' }
    return { path: '/login' }
  }
})

export default router
