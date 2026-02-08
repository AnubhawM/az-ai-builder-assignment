// src/App.tsx
import React, { useState } from 'react';
import axios from 'axios';
import { ToastContainer, toast } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import MainLayout from './layouts/MainLayout';
import Card from './components/ui/Card';
import TextBox from './components/TextBox';
import ResearchBot from './components/ResearchBot';
import { GenerateRequest, GenerateResponse } from './types/api';

const App: React.FC = () => {
  const [prompt, setPrompt] = useState<string>('');
  const [response, setResponse] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);

  const generateResponse = async () => {
    if (!prompt.trim()) {
      toast.error('Please enter a prompt!');
      return;
    }

    try {
      setLoading(true);
      const response = await axios.post<GenerateResponse>(
        `${import.meta.env.VITE_API_URL}/generate`,
        { prompt } as GenerateRequest,
        {
          headers: {
            'Content-Type': 'application/json'
          }
        }
      );
      setResponse(response.data.response);
    } catch (error) {
      console.error(error);
      toast.error('Failed to generate response. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <MainLayout>
      <div className="w-screen px-6 py-8">
        <div className="max-w-7xl mx-auto">
          <Card className="max-w-2xl mx-auto">
            <textarea
              className="w-full p-4 bg-gray-50 border border-gray-200 rounded-md mb-4 resize-none focus:ring-2 focus:ring-blue-500 outline-none text-gray-900 placeholder:text-gray-400"
              rows={5}
              placeholder="Enter a prompt..."
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
            <button
              className={`w-full px-6 py-2 rounded-md text-white font-medium ${loading ? 'bg-gray-400' : 'bg-blue-500 hover:bg-blue-600 shadow-lg'
                }`}
              onClick={generateResponse}
              disabled={loading}
            >
              {loading ? 'Generating...' : 'Generate Chat Response'}
            </button>
            {response && <TextBox response={response} />}
          </Card>

          <ResearchBot />
        </div>
      </div>
      <ToastContainer />
    </MainLayout>
  );
};

export default App;
