import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { authAPI } from '../services/api';

interface User {
  id: string;
  name: string;
  email: string;
  department: string;
  environment_access: Record<string, boolean>;
  manager_email?: string;
}

interface LoginResponse {
  access_token?: string;
  message?: string;
  requires_otp?: boolean;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<LoginResponse>;
  register: (userData: Record<string, unknown>) => Promise<LoginResponse>;
  verifyOTP: (email: string, otp: string) => Promise<LoginResponse>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);



export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('token');
    console.log('AuthContext: Initializing with token:', token ? 'exists' : 'none');
    
    if (token) {
      // Validate token format before using it
      try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        const currentTime = Date.now() / 1000;
        
        if (payload.exp < currentTime) {
          console.log('AuthContext: Token expired, clearing auth');
          localStorage.removeItem('token');
          localStorage.removeItem('cached_user_data');
          setUser(null);
          setLoading(false);
          return;
        }
        
        fetchProfile();
      } catch (error) {
        console.log('AuthContext: Invalid token format, clearing auth');
        localStorage.removeItem('token');
        localStorage.removeItem('cached_user_data');
        setUser(null);
        setLoading(false);
      }
    } else {
      console.log('AuthContext: No token found, user needs to login');
      setLoading(false);
    }
  }, []);

  const fetchProfile = async () => {
    try {
      console.log('AuthContext: Fetching user profile...');
      
      const response = await authAPI.getProfile();
      console.log('AuthContext: Profile response status:', response.status);
      const userData = response.data;
      console.log('AuthContext: User data received:', userData);
      
      // Validate user data
      if (!userData.name || !userData.email || !userData.department) {
        console.error('AuthContext: Invalid user data received', userData);
        throw new Error('Invalid user data');
      }
      
      // Cache the user data to detect changes
      const cachedUser = localStorage.getItem('cached_user_data');
      if (cachedUser) {
        const previousUser = JSON.parse(cachedUser);
        
        // Check if environment access changed
        const envAccessChanged = JSON.stringify(previousUser.environment_access) !== JSON.stringify(userData.environment_access);
        
        if (envAccessChanged) {
          console.log('Environment access updated');
        }
      }
      
      // Update cached user data
      localStorage.setItem('cached_user_data', JSON.stringify(userData));
      
      setUser(userData);
      console.log('AuthContext: User state updated successfully');
    } catch (error) {
      console.error('Failed to fetch profile:', error);
      console.error('Error details:', {
        message: error.message,
        status: error.response?.status,
        statusText: error.response?.statusText,
        data: error.response?.data
      });
      
      // Only clear auth if it's actually an auth error
      if (error.response?.status === 401 || error.response?.status === 403) {
        console.log('AuthContext: Clearing invalid authentication');
        localStorage.removeItem('token');
        localStorage.removeItem('cached_user_data');
        setUser(null);
      } else {
        console.log('AuthContext: Network error, keeping auth state');
      }
    } finally {
      setLoading(false);
    }
  };

  const refreshUser = async () => {
    if (!user) return;
    
    try {
      const response = await authAPI.getProfile();
      const userData = response.data;
      
      // Compare with current user data
      const envAccessChanged = JSON.stringify(user.environment_access) !== JSON.stringify(userData.environment_access);
      
      if (envAccessChanged) {
        console.log('Environment access refreshed');
        
        // Update cached user data
        localStorage.setItem('cached_user_data', JSON.stringify(userData));
        
        // Force update user state
        setUser(userData);
      } else {
        setUser(userData);
      }
    } catch (error) {
      console.error('Failed to refresh user data');
      // Don't throw error to prevent breaking the UI
    }
  };

  const login = async (email: string, password: string) => {
    const response = await authAPI.login(email, password);
    return response.data;
  };

  const register = async (userData: any) => {
    const response = await authAPI.register(userData);
    return response.data;
  };

  const verifyOTP = async (email: string, otp: string) => {
    try {
      console.log('AuthContext: Verifying OTP for:', email);
      const response = await authAPI.verifyOTP(email, otp);
      console.log('AuthContext: OTP verification response:', response.status);
      
      const { access_token } = response.data;
      console.log('AuthContext: Received access token:', access_token ? 'yes' : 'no');
      
      if (!access_token) {
        throw new Error('No access token received');
      }
      
      localStorage.setItem('token', access_token);
      localStorage.setItem('login_time', Date.now().toString());
      
      // Clear any existing localStorage chat data for fresh start on new login
      Object.keys(localStorage).forEach(key => {
        if (key.startsWith('chat_messages_') || 
            key.startsWith('chat_key_')) {
          localStorage.removeItem(key);
        }
      });
      // Don't clear sessionStorage here - let chat component handle it
      
      console.log('AuthContext: Token stored, fetching profile...');
      await fetchProfile();
      console.log('AuthContext: OTP verification complete');
      
      return response.data;
    } catch (error) {
      console.error('OTP verification failed:', error);
      console.error('Error details:', {
        message: error.message,
        status: error.response?.status,
        data: error.response?.data
      });
      throw error;
    }
  };

  const logout = () => {
    try {
      // Clear only authentication-related data
      localStorage.removeItem('token');
      localStorage.removeItem('cached_user_data');
      localStorage.removeItem('login_time');
      
      // Clear all chat-related data for fresh start
      Object.keys(localStorage).forEach(key => {
        if (key.startsWith('chat_messages_') || 
            key.startsWith('chat_key_') || 
            key.startsWith('greeting_shown_')) {
          localStorage.removeItem(key);
        }
      });
      
      // Keep notifications and dashboard data
      // localStorage.removeItem('layout_notifications'); // KEEP
      // localStorage.removeItem('notification_sound_enabled'); // KEEP
      // localStorage.removeItem('real_time_updates_enabled'); // KEEP
      
      // Clear only chat-specific data
      localStorage.removeItem('chat_notifications');
      
      // Clear session storage completely for fresh start
      sessionStorage.clear();
      
      // Clear user state
      setUser(null);
      
    } catch (error) {
      console.error('Error during logout cleanup');
      // Still clear user state even if cleanup fails
      setUser(null);
    }
  };

  return (
    <AuthContext.Provider value={{
      user,
      loading,
      login,
      register,
      verifyOTP,
      logout,
      refreshUser
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};