import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';

const Quiz = ({ initialState }) => {
    const { t } = useTranslation();
    const cards = initialState?.cards || [];
    const [currentIndex, setCurrentIndex] = useState(0);
    const [score, setScore] = useState(0);
    const [showResult, setShowResult] = useState(false);
    const [selectedChoice, setSelectedChoice] = useState(null);
    const [isCorrect, setIsCorrect] = useState(null);
    const [showHint, setShowHint] = useState(false);

    const currentCard = cards[currentIndex];

    const handleChoice = (choiceIndex) => {
        if (selectedChoice !== null) return; // Block interaction

        const correct = choiceIndex === currentCard.correct_index;
        setSelectedChoice(choiceIndex);
        setIsCorrect(correct);
        if (correct) setScore(s => s + 1);
    };

    const nextQuestion = () => {
        if (currentIndex < cards.length - 1) {
            setCurrentIndex(prev => prev + 1);
            setSelectedChoice(null);
            setIsCorrect(null);
            setShowHint(false);
        } else {
            setShowResult(true);
        }
    };

    const restart = () => {
        setCurrentIndex(0);
        setScore(0);
        setShowResult(false);
        setSelectedChoice(null);
        setIsCorrect(null);
        setShowHint(false);
    };

    if (!currentCard && !showResult) return <div>{t('quiz.dataError')}</div>;

    return (
        <div className="quiz-container">
            {showResult ? (
                <div className="quiz-card results-card">
                    <h2>{t('quiz.completed')}</h2>
                    <p>{t('quiz.score', { score, total: cards.length })}</p>
                    <button className="next-button" onClick={restart}>{t('quiz.tryAgain')}</button>
                </div>
            ) : (
                <div className="quiz-card">
                    <div className="quiz-header">
                        <span>{t('quiz.question', { current: currentIndex + 1, total: cards.length })}</span>
                        <div className="progress-bar-container">
                            <div className="progress-bar-fill" style={{ width: `${((currentIndex + 1) / cards.length) * 100}%` }}></div>
                        </div>
                    </div>
                    <div className="quiz-body">
                        <h2>{currentCard.question}</h2>
                        <ul className="choices-grid">
                            {currentCard.choices.map((choice, idx) => {
                                let className = 'choice-item';
                                if (selectedChoice !== null) {
                                    className += ' disabled';
                                    if (idx === currentCard.correct_index) className += ' correct';
                                    else if (idx === selectedChoice) className += ' incorrect';
                                }
                                return (
                                    <li key={idx} className={className} onClick={() => handleChoice(idx)}>
                                        <span>{choice}</span>
                                    </li>
                                );
                            })}
                        </ul>
                    </div>
                    <div className="quiz-footer">
                        <div className="hint-section">
                            <button className="hint-button" onClick={() => setShowHint(!showHint)}>{t('quiz.hint')}</button>
                            <p className={`hint-text ${showHint ? 'visible' : ''}`}>{currentCard.hint}</p>
                        </div>
                        {selectedChoice !== null && (
                            <button className="next-button" style={{display: 'block'}} onClick={nextQuestion}>{t('quiz.next')}</button>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};

export default Quiz;
