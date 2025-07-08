CREATE TABLE admins(
    admin_id varchar(20) primary key,
    admin_username varchar(50) not null unique,
    admin_password varchar(150) not null,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE users(
    user_id varchar(20) primary key,
    username VARCHAR(50) NOT NULL unique,
    password varchar(150) not null,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    name text not null,
    birth_date date not null,
    gender varchar(6) not null check(gender in ('Male', 'Female')),
    email VARCHAR(100) UNIQUE,
    address text,
    avatar_url TEXT DEFAULT 'https://www.pngall.com/wp-content/uploads/12/Avatar-Profile-PNG-Image.png'
);

CREATE TABLE students(
    student_id varchar(20) references users(user_id) ON DELETE CASCADE primary key,
    introduction text,
    hobby text
);

CREATE TABLE teachers(
    teacher_id varchar(20) REFERENCES users(user_id) ON DELETE CASCADE PRIMARY KEY,
    introduction text,
    degree text,
    experience text,
    teaching_style text,
    hobby text,
    avg_rate NUMERIC(3,2) DEFAULT 0,
    is_finding_student boolean DEFAULT true
);

CREATE TABLE subjects (
    subject_id varchar(20) PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);

CREATE TABLE classes (
    class_id varchar(20) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    subject_id varchar(20) REFERENCES subjects(subject_id) ON DELETE SET NULL,
    teacher_id varchar(20) references teachers(teacher_id) on delete cascade
);

CREATE TABLE class_Student (
    student_id varchar(20) REFERENCES students(student_id) ON DELETE CASCADE,
    class_id varchar(20) REFERENCES classes(class_id) ON DELETE CASCADE,
    PRIMARY KEY (student_id, class_id)
);

CREATE TABLE reviews (
    review_id varchar(20) PRIMARY KEY,
    student_id varchar(20) REFERENCES students(student_id) ON DELETE CASCADE,
    teacher_id varchar(20) REFERENCES teachers(teacher_id) ON DELETE CASCADE,
    rate INT CHECK (rate >= 0 AND rate <= 5),
    comment TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE posts (
    post_id varchar(20) PRIMARY KEY,
    user_id varchar(20) REFERENCES users(user_id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    status varchar(20) default 'private' check(status in('private', 'public')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE  TABLE post_likes(
    like_id varchar(20) primary key,
    post_id varchar(20) references posts(post_id) on delete cascade,
    owner_id varchar(20) references users(user_id) on delete cascade
);

create table post_comments(
    post_comment_id varchar(20) primary key,
    post_id varchar(20) references posts(post_id) on delete cascade,
    owner_id varchar(20) references users(user_id) on delete cascade,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE suitable_teachers(
	post_id varchar(20) references posts(post_id) on delete cascade,
	teacher_id varchar(20) references teachers(teacher_id) on delete cascade,
	teacher_name VARCHAR(50),
	email VARCHAR(100),
	reason text,
	primary key(post_id, teacher_id)
);

-- LOGS_AI_MATCHING
CREATE TABLE logs_AI_matching (
    matching_log_id varchar(20) PRIMARY KEY,
    student_id varchar(20) REFERENCES students(student_id) ON DELETE CASCADE,
	teacher_id varchar(20) REFERENCES teachers(teacher_id) ON DELETE CASCADE,
    class_id varchar(20) REFERENCES classes(class_id) ON DELETE SET NULL,
    post_id varchar(20) REFERENCES posts(post_id) ON DELETE SET NULL,
	status VARCHAR(50) DEFAULT 'pending' check(status in ('pending', 'matched')),
    matched_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
	UNIQUE (post_id, status)
);

CREATE TABLE conversations (
    conversation_id varchar(20) primary key,
    conversation_name varchar(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

create table participants_conversation(
    conversation_id varchar(20) references conversations(conversation_id) ON DELETE CASCADE,
    user_id varchar(20) references users(user_id) ON DELETE CASCADE,
    primary key(conversation_id, user_id)
);

CREATE TABLE messages (
    message_id serial PRIMARY KEY,
    conversation_id VARCHAR(50) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    sender_id VARCHAR(20) REFERENCES users(user_id) ON DELETE CASCADE,
    message_text TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- tạo index cho bảng messages để mỗi khi query tin nhắn trong một conversations thì việc order by sẽ nhanh chóng hơn so với tạo trigger tự động tăng message_id
CREATE INDEX idx_messages_convo_created_at
ON messages(conversation_id, created_at);

--SELECT *
--FROM messages
--WHERE conversation_id = 'conv_001'
--ORDER BY created_at;

-- tạo function update avg_rate của giáo viên
CREATE OR REPLACE FUNCTION update_teacher_avg_rate()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE teachers
    SET avg_rate = (
        SELECT ROUND(AVG(rate)::numeric, 2)
        FROM reviews
        WHERE teacher_id = NEW.teacher_id
    )
    WHERE user_id = NEW.teacher_id;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- trigger update rate
-- Khi thêm review
CREATE TRIGGER trg_update_avg_rate_after_insert
AFTER INSERT ON reviews
FOR EACH ROW
EXECUTE FUNCTION update_teacher_avg_rate();

-- Khi xoá review
CREATE TRIGGER trg_update_avg_rate_after_delete
AFTER DELETE ON reviews
FOR EACH ROW
EXECUTE FUNCTION update_teacher_avg_rate();

-- Khi chỉnh sửa điểm số review
CREATE TRIGGER trg_update_avg_rate_after_update
AFTER UPDATE OF rate ON reviews
FOR EACH ROW
EXECUTE FUNCTION update_teacher_avg_rate();
