// src/App.tsx
import React, { useState } from 'react';
import axios from 'axios';
import { ToastContainer, toast } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import MainLayout from './layouts/MainLayout';
import Card from './components/ui/Card';
import ResearchBot from './components/ResearchBot';
import PowerPointGenerator from './components/PowerPointGenerator';

interface ProposalResponse {
  response: string;
  type?: 'google_doc_url' | 'text';
  message?: string;
}

const App: React.FC = () => {
  const [topic, setTopic] = useState<string>('');
  const [result, setResult] = useState<ProposalResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [loadingStatus, setLoadingStatus] = useState<string>('');

  const generateProposal = async () => {
    if (!topic.trim()) {
      toast.error('Please enter a research topic!');
      return;
    }

    try {
      setLoading(true);
      setResult(null);

      // Simulate progress updates
      setLoadingStatus('🔍 Researching topic...');
      const statusUpdates = [
        { delay: 5000, status: '📚 Gathering information...' },
        { delay: 15000, status: '📝 Writing proposal...' },
        { delay: 30000, status: '📄 Creating Google Doc...' },
        { delay: 60000, status: '⏳ Still working... (this may take a few minutes)' },
      ];

      const timeouts = statusUpdates.map(({ delay, status }) =>
        setTimeout(() => setLoadingStatus(status), delay)
      );

      const response = await axios.post<ProposalResponse>(
        `${import.meta.env.VITE_API_URL}/generate`,
        { prompt: topic },
        {
          headers: { 'Content-Type': 'application/json' },
          timeout: 360000 // 6 minute timeout
        }
      );

      // Clear all status timeouts
      timeouts.forEach(t => clearTimeout(t));

      setResult(response.data);

      if (response.data.type === 'google_doc_url') {
        toast.success('🎉 Project proposal created as a Google Doc!');
      } else {
        toast.success('Proposal generated!');
      }
    } catch (error) {
      console.error(error);
      toast.error('Failed to generate proposal. Please try again.');
    } finally {
      setLoading(false);
      setLoadingStatus('');
    }
  };

  return (
    <MainLayout>
      <div className="w-screen px-6 py-8">
        <div className="max-w-7xl mx-auto">
          {/* PowerPoint Generator - New Primary Feature */}
          <PowerPointGenerator />

          {/* Divider */}
          <div className="flex items-center my-12 max-w-2xl mx-auto">
            <div className="flex-1 border-t border-gray-300"></div>
            <span className="px-4 text-gray-500 text-sm font-medium">OR TRY OTHER TOOLS</span>
            <div className="flex-1 border-t border-gray-300"></div>
          </div>

          <Card className="max-w-2xl mx-auto">
            <h2 className="text-2xl font-bold mb-2 text-gray-800 flex items-center">
              <span className="mr-2">🦞</span> Research Proposal Generator
            </h2>
            <p className="text-gray-600 mb-6">
              Enter a research topic below. OpenClaw will research it and create a comprehensive project proposal as a Google Doc.
            </p>

            <textarea
              className="w-full p-4 bg-gray-50 border border-gray-200 rounded-md mb-4 resize-none focus:ring-2 focus:ring-blue-500 outline-none text-gray-900 placeholder:text-gray-400"
              rows={4}
              placeholder="e.g., The impact of AI on renewable energy optimization..."
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              disabled={loading}
            />

            <button
              className={`w-full px-6 py-3 rounded-md text-white font-semibold text-lg transition-all ${loading
                ? 'bg-gray-400 cursor-not-allowed'
                : 'bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 shadow-lg'
                }`}
              onClick={generateProposal}
              disabled={loading}
            >
              {loading ? (
                <div className="flex items-center justify-center">
                  <span className="animate-spin mr-2">⏳</span>
                  {loadingStatus || 'Processing...'}
                </div>
              ) : (
                '📄 Generate Project Proposal'
              )}
            </button>

            {result && (
              <div className="mt-6 p-6 bg-green-50 border border-green-200 rounded-lg">
                <h3 className="text-lg font-bold text-green-800 mb-4">✅ Research Proposal</h3>
                <div className="bg-white p-4 rounded border border-gray-200 whitespace-pre-wrap text-gray-700 max-h-[500px] overflow-y-auto prose prose-sm">
                  {result.response}
                </div>
              </div>
            )}
          </Card>

          <ResearchBot />
        </div>
      </div>
      <ToastContainer />
    </MainLayout>
  );
};

export default App;

