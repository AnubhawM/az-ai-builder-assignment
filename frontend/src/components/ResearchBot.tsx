import React, { useState } from 'react';
import axios from 'axios';
import { toast } from 'react-toastify';
import Card from './ui/Card';

const ResearchBot: React.FC = () => {
    const [topic, setTopic] = useState<string>('');
    const [loading, setLoading] = useState<boolean>(false);
    const [result, setResult] = useState<{ message: string; file_name: string } | null>(null);

    const startResearch = async () => {
        if (!topic.trim()) {
            toast.error('Please enter a research topic!');
            return;
        }

        try {
            setLoading(true);
            setResult(null);

            const response = await axios.post(
                `${import.meta.env.VITE_API_URL}/research`,
                { topic },
                {
                    headers: {
                        'Content-Type': 'application/json'
                    }
                }
            );

            setResult(response.data);
            toast.success('Research completed successfully!');
        } catch (error: any) {
            console.error(error);
            const errorMsg = error.response?.data?.error || 'Failed to start research. Please try again.';
            toast.error(errorMsg);
        } finally {
            setLoading(false);
        }
    };

    return (
        <Card className="max-w-2xl mx-auto mt-8 border-t-4 border-blue-500 shadow-2xl">
            <h2 className="text-2xl font-bold mb-4 text-gray-800 flex items-center">
                <span className="mr-2">🦞</span> Researcher Bot
            </h2>
            <p className="text-gray-600 mb-6">
                Enter a topic below, and our automated researcher will explore it and create a PowerPoint presentation for you.
            </p>

            <div className="space-y-4">
                <input
                    type="text"
                    className="w-full p-4 bg-gray-50 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none transition-all text-gray-900 placeholder:text-gray-400"
                    placeholder="e.g., The impact of AI on renewable energy..."
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    disabled={loading}
                />

                <button
                    className={`w-full px-6 py-3 rounded-lg text-white font-semibold text-lg shadow-md transition-all ${loading
                        ? 'bg-gray-400 cursor-not-allowed'
                        : 'bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 active:scale-95'
                        }`}
                    onClick={startResearch}
                    disabled={loading}
                >
                    {loading ? (
                        <div className="flex items-center justify-center">
                            <span className="animate-spin mr-2">⏳</span>
                            Researching & Generating PPT...
                        </div>
                    ) : (
                        'Generate Presentation'
                    )}
                </button>
            </div>

            {result && (
                <div className="mt-8 p-6 bg-green-50 border border-green-200 rounded-lg transition-all transform scale-100">
                    <h3 className="text-lg font-bold text-green-800 mb-2">Success!</h3>
                    <p className="text-green-700 mb-4">{result.message}</p>
                    <div className="flex items-center p-4 bg-white border border-green-100 rounded-lg shadow-sm">
                        <span className="text-3xl mr-4">📊</span>
                        <div>
                            <p className="text-sm font-semibold text-gray-900">{result.file_name}</p>
                            <p className="text-xs text-gray-500">The file is saved in your project root directory.</p>
                        </div>
                    </div>
                </div>
            )}
        </Card>
    );
};

export default ResearchBot;
