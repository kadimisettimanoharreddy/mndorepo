import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',  // Skip ngrok browser warning
  },
});

api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

api.interceptors.response.use(
  (response) => {
    return response;
  },
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      delete api.defaults.headers.common['Authorization'];
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export const infrastructureAPI = {
  getRequests: () => api.get('/infrastructure/requests'),
  createRequest: (data: any) => api.post('/infrastructure/request', data),
  getRequest: (id: string) => api.get(`/infrastructure/requests/${id}`),
  updateRequest: (id: string, data: any) => api.put(`/infrastructure/requests/${id}`, data),
  deleteRequest: (id: string) => api.delete(`/infrastructure/requests/${id}`),
  clearUserRequests: () => api.delete('/api/user/clear-requests'),
  getCloudProviders: () => api.get('/infrastructure/cloud-providers'),
  getEnvironments: () => api.get('/infrastructure/environments'),
  getResourceTypes: () => api.get('/infrastructure/resource-types'),
};

export const monitoringAPI = {
  getUserInstances: () => api.get('/monitoring/instances'),
  getInstanceStatus: (instanceId: string) => api.get(`/monitoring/instance/${instanceId}/status`),
  getInstanceMetrics: (instanceId: string) => api.get(`/monitoring/instance/${instanceId}/metrics`),
  startInstance: (instanceId: string) => api.post(`/monitoring/instance/${instanceId}/start`),
  stopInstance: (instanceId: string) => api.post(`/monitoring/instance/${instanceId}/stop`),
  restartInstance: (instanceId: string) => api.post(`/monitoring/instance/${instanceId}/restart`),
  terminateInstance: (instanceId: string) => api.post(`/monitoring/instance/${instanceId}/terminate`),
};

export const authAPI = {
  login: (email: string, password: string) => api.post('/auth/login', { email, password }),
  register: (userData: any) => api.post('/auth/register', userData),
  verifyOTP: (email: string, otp: string) => api.post('/auth/verify-otp', { email, otp }),
  getProfile: () => api.get('/auth/profile'),
  updateProfile: (data: any) => api.put('/auth/profile', data),
  changePassword: (data: any) => api.post('/auth/change-password', data),
  logout: () => api.post('/auth/logout'),
};

export const chatAPI = {
  sendMessage: (message: string) => api.post('/chat/message', { message }),
  getChatHistory: () => api.get('/chat/history'),
  clearChatHistory: () => api.delete('/chat/history'),
};

export const notificationAPI = {
  getNotifications: () => api.get('/api/notifications'),
  markAsRead: (id: string) => api.post(`/api/notifications/${id}/read`),
  markAllAsRead: () => api.post('/api/notifications/mark-all-read'),
  clearAll: () => api.post('/api/notifications/clear-all'),
  getUnreadCount: () => api.get('/api/notifications/unread-count'),
};

export const settingsAPI = {
  getSettings: () => api.get('/settings'),
  updateSettings: (data: any) => api.put('/settings', data),
  getEnvironmentAccess: () => api.get('/settings/environment-access'),
  requestEnvironmentAccess: (environment: string) => api.post('/settings/request-environment-access', { environment }),
};

export default api;