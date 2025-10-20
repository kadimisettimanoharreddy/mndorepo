import React, { createContext, useContext, useEffect, useState, useRef } from 'react';
import { useAuth } from './AuthContext';

interface WebSocketContextType {
  ws: WebSocket | null;
  connected: boolean;
  sendMessage: (message: any) => void;
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined);

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  const [ws, setWs] = useState<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const { user } = useAuth();
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>();
  const wsRef = useRef<WebSocket | null>(null);

  const connectWebSocket = () => {
    const token = localStorage.getItem('token');
    if (!token || !user) return;

    // Prevent duplicate connections
    if (wsRef.current && wsRef.current.readyState === WebSocket.CONNECTING) {
      return;
    }

    // Close existing connection
    if (wsRef.current) {
      wsRef.current.close();
    }

    const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    const wsUrl = `${apiUrl.replace('http://', 'ws://').replace('https://', 'wss://')}/ws/chat?token=${token}`;
    const websocket = new WebSocket(wsUrl);
    wsRef.current = websocket;

    websocket.onopen = () => {
      console.log('🔗 Global WebSocket connected');
      setConnected(true);
      setWs(websocket);
      
      // Clear any pending reconnection
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };

    websocket.onclose = (event) => {
      console.log('❌ Global WebSocket disconnected', event.code, event.reason);
      setConnected(false);
      setWs(null);
      wsRef.current = null;
      
      // Auto-reconnect only for unexpected disconnections (not dev hot reload)
      if (event.code !== 1000 && event.code !== 1001 && event.code !== 1005 && event.code !== 1012 && user && localStorage.getItem('token')) {
        console.log('🔄 Attempting to reconnect...');
        reconnectTimeoutRef.current = setTimeout(() => {
          connectWebSocket();
        }, 1000);
      } else if (event.code === 1005) {
        console.log('🔥 Hot reload detected - will reconnect automatically');
      }
    };

    websocket.onerror = (error) => {
      console.error('⚠️ Global WebSocket error occurred:', error);
      setConnected(false);
      setWs(null);
    };
    
    // Remove custom event dispatch to prevent duplicate processing
    websocket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        console.log('📨 WebSocket message received:', data.type);
        // Message will be handled by individual component listeners
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };
  };

  const sendMessage = (message: any) => {
    if (wsRef.current && connected) {
      wsRef.current.send(JSON.stringify(message));
    }
  };

  useEffect(() => {
    if (user) {
      connectWebSocket();
    } else {
      // User logged out, close connection
      if (wsRef.current) {
        wsRef.current.close();
      }
      setConnected(false);
      setWs(null);
    }

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [user]);

  return (
    <WebSocketContext.Provider value={{ ws, connected, sendMessage }}>
      {children}
    </WebSocketContext.Provider>
  );
}

export function useWebSocket() {
  const context = useContext(WebSocketContext);
  if (!context) {
    throw new Error('useWebSocket must be used within WebSocketProvider');
  }
  return context;
}