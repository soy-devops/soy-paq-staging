import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [{ path: '/soypaq-wms', component: { template: '<div />' } }],
})
